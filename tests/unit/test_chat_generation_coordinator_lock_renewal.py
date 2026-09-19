"""アクティブジョブロックのTTL更新（所有トークン確認つき）を検証するテスト。

Tests for renewing the active-job lock's TTL while verifying the owner token.
"""

import threading
import time
import unittest

from services.chat_generation_coordinator import ChatGenerationCoordinator


# 日本語: TTLを実際に失効させる疑似Redis。更新テストでは「本当に延長されたか」を
# 確認する必要があるため、test_chat_generation_stop.py の疑似Redis（TTLを無視する）
# は使わず、ここだけで完結する実装を用意する。
# English: A fake Redis that actually expires TTLs. The renewal tests need to prove the TTL
# was genuinely extended, so this does not reuse test_chat_generation_stop.py's fake (which
# ignores TTL); it is self-contained instead.
class _FakeExpiringRedis:
    def __init__(self):
        self._lock = threading.Lock()
        self._values: dict[str, tuple[str, float | None]] = {}

    def _alive_locked(self, key: str, now: float) -> bool:
        entry = self._values.get(key)
        if entry is None:
            return False
        _value, expires_at = entry
        if expires_at is not None and now >= expires_at:
            del self._values[key]
            return False
        return True

    def set(self, key, value, nx=False, ex=None):
        now = time.monotonic()
        with self._lock:
            if nx and self._alive_locked(key, now):
                return False
            expires_at = now + ex if ex is not None else None
            self._values[key] = (value, expires_at)
            return True

    def exists(self, key):
        with self._lock:
            return 1 if self._alive_locked(key, time.monotonic()) else 0

    def delete(self, key):
        with self._lock:
            existed = key in self._values
            self._values.pop(key, None)
            return 1 if existed else 0

    # 日本語: release（token のみ）と refresh（token + ttl）の両方の Lua スクリプトを模擬する。
    # English: Emulates both the release script (token only) and the refresh script (token + ttl).
    def eval(self, script, key_count, key, *args):
        del script, key_count
        now = time.monotonic()
        with self._lock:
            if not self._alive_locked(key, now):
                return 0
            value, _expires_at = self._values[key]
            token = args[0]
            if value != token:
                return 0
            if len(args) >= 2:
                ttl = float(args[1])
                self._values[key] = (value, now + ttl)
                return 1
            del self._values[key]
            return 1

    # 日本語: イベント配信（publish_event）が使うパイプラインを模擬する。
    # このテストではイベント内容そのものは検証しないため、コマンドは素通しでよい。
    # English: Emulates the pipeline publish_event uses. These tests do not assert on event
    # content, so the queued commands can simply be dropped.
    def pipeline(self):
        return _NoOpPipeline()


class _NoOpPipeline:
    def rpush(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    def publish(self, *args, **kwargs):
        return self

    def execute(self):
        return True


def _build_coordinator(redis_client, *, ttl_seconds: int = 900) -> ChatGenerationCoordinator:
    return ChatGenerationCoordinator(
        job_retention_seconds=300,
        active_job_lock_ttl_seconds=ttl_seconds,
        distributed_stream_idle_timeout_seconds=60,
        sse_heartbeat_seconds=15.0,
        remote_cancel_timeout_seconds=1.0,
        cancel_local_job=lambda job_key: False,
        has_running_local_jobs=lambda: False,
        redis_client_getter=lambda: redis_client,
    )


class RefreshActiveJobLockTestCase(unittest.TestCase):
    def setUp(self):
        self.redis = _FakeExpiringRedis()
        self.job_key = "user:1:room-1"

    # 日本語: 所有トークンが一致すればTTLが延長されることを確認する。
    # English: Verify a matching owner token extends the TTL.
    def test_renews_when_the_owner_token_matches(self):
        coordinator = _build_coordinator(self.redis, ttl_seconds=1)
        acquired, token = coordinator.try_acquire_active_job_lock(self.job_key)
        self.assertTrue(acquired)

        # TTL(1秒)を超えて待っても、更新すれば生き残ることを確認する。
        # Even past the 1s TTL, a renewal should keep the lock alive.
        time.sleep(1.2)
        self.assertFalse(coordinator.has_active_lock(self.job_key))

        acquired, token = coordinator.try_acquire_active_job_lock(self.job_key)
        self.assertTrue(acquired)
        # 更新のたびにTTLが1秒へリセットされるので、TTLの半分ごとに更新し続ければ、
        # 1回のTTLよりずっと長く生き残ることを確認できる。
        # Each renewal resets the TTL to 1s, so renewing every half-TTL should keep the lock
        # alive far longer than a single TTL window ever would.
        for _ in range(4):
            time.sleep(0.5)
            self.assertTrue(coordinator.refresh_active_job_lock(self.job_key, token))
        self.assertTrue(coordinator.has_active_lock(self.job_key))

    # 日本語: 別ワーカーがロックを取り直した後は、旧トークンでの更新が失敗することを確認する
    # （所有者以外は更新できないという要件の核心）。
    # English: Verify a stale token cannot renew a lock another worker has re-acquired since —
    # the core requirement that only the owner may extend it.
    def test_does_not_renew_a_lock_now_owned_by_another_worker(self):
        coordinator = _build_coordinator(self.redis, ttl_seconds=900)
        acquired, old_token = coordinator.try_acquire_active_job_lock(self.job_key)
        self.assertTrue(acquired)

        # 別ワーカーがロックを強制解放して取り直したことを模擬する。
        # Simulate another worker force-releasing and re-acquiring the lock.
        coordinator.force_release_active_job_lock(self.job_key)
        reacquired, new_token = coordinator.try_acquire_active_job_lock(self.job_key)
        self.assertTrue(reacquired)
        self.assertNotEqual(old_token, new_token)

        self.assertFalse(coordinator.refresh_active_job_lock(self.job_key, old_token))
        # 新しい所有者のロックはそのまま残っていること。
        # The new owner's lock must remain untouched.
        self.assertTrue(coordinator.has_active_lock(self.job_key))

    # 日本語: トークンが無い（Redis未使用や取得失敗）場合は何もせず False を返す。
    # English: With no token (Redis unused, or acquisition failed) it does nothing and returns False.
    def test_returns_false_without_a_token(self):
        coordinator = _build_coordinator(self.redis)
        self.assertFalse(coordinator.refresh_active_job_lock(self.job_key, None))

    # 日本語: Redis呼び出しが例外を送出しても、更新失敗として扱い呼び出し元へ伝播させない。
    # English: A Redis-side exception is treated as a failed renewal, never propagated.
    def test_fails_closed_when_redis_raises(self):
        class _RaisingRedis(_FakeExpiringRedis):
            def eval(self, script, key_count, key, *args):
                raise ConnectionError("redis unavailable")

        redis_client = _RaisingRedis()
        coordinator = _build_coordinator(redis_client)
        acquired, token = coordinator.try_acquire_active_job_lock(self.job_key)
        self.assertTrue(acquired)
        self.assertFalse(coordinator.refresh_active_job_lock(self.job_key, token))


# 日本語: ジョブが実行中の間、`ChatGenerationJob` の更新スレッドが実際にロックのTTLを
# 保ち続けることをエンドツーエンドで確認する。TTLより長く回るターンでもロックが
# 失効しない（＝別ワーカーの二重生成を防げる）ことが本題。
# English: End-to-end check that `ChatGenerationJob`'s renewal thread keeps the lock's TTL
# alive for as long as the job runs. The point is that a turn outlasting the TTL still keeps
# its lock, which is what prevents another worker from starting a duplicate generation.
class ChatGenerationJobLockRenewalTestCase(unittest.TestCase):
    def test_lock_survives_past_its_nominal_ttl_while_the_job_keeps_running(self):
        from unittest.mock import patch

        from services.chat_generation import ChatGenerationService

        redis_client = _FakeExpiringRedis()
        # TTLを3で割った値がそのまま更新間隔になる（1秒未満には丸めない）ため、
        # 更新間隔がTTLよりはっきり短くなるようTTLは十分な大きさにする。
        # The renewal interval is TTL/3 (never rounded below 1s), so pick a TTL large enough
        # that the interval stays clearly shorter than the TTL itself.
        service = ChatGenerationService(
            redis_client_getter=lambda: redis_client,
            active_job_lock_ttl_seconds=6,
        )
        job_key = "user:1:room-1"
        lock_key = f"chat_generation:active:{job_key}"

        def _slow_stream(messages, model, tools=None, generation_phase="default"):
            del messages, model, tools, generation_phase
            yield (
                '<turn_state_update>{"objective":"hi","unresolved_questions":[],'
                '"facts":[],"evidence_ids":[],"ready_to_answer":true}</turn_state_update>'
            )
            for _ in range(150):
                time.sleep(0.07)
                yield "chunk "

        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=_slow_stream,
        ):
            job = service.start_generation_job(
                job_key,
                conversation_messages=[{"role": "user", "content": "hi"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response, **kwargs: None,
            )
            deadline = time.monotonic() + 5
            while not redis_client.exists(lock_key) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(redis_client.exists(lock_key))

            # 何もしなければ6秒（TTL既定値）で消えるはずのロックが、8秒経っても
            # 定期更新により生き残っていることを確認する。ジョブ自体もまだ実行中であること
            # を確認し、「TTL切れではなくジョブが先に終わっただけ」の誤検知を防ぐ。
            # Without renewal the lock would vanish after 6s (the TTL). Confirm it survives 8s
            # instead, and that the job is still running so this is not a false pass from the
            # job simply finishing before the TTL check.
            time.sleep(8.0)
            self.assertFalse(job.is_done)
            self.assertTrue(redis_client.exists(lock_key))

            service.reset_in_memory_state(cancel_running=True)
            self.assertTrue(job.wait(timeout=5.0))

        # ジョブ終了後は更新スレッドも止まり、ロックは通常の完了経路で解放される。
        # After the job ends the renewal thread stops too, and the lock is released through
        # the normal completion path.
        self.assertFalse(redis_client.exists(lock_key))


if __name__ == "__main__":
    unittest.main()
