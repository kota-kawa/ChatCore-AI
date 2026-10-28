"""Sample data a demo account starts with, so each feature has something to show on first open.

既定のタスクは通常の新規ユーザーと同じくコピーするので、ここではそれ以外（プロジェクト、
チャット履歴、メモ、個人のコンテキスト、Skill）を入れる。デモ用ユーザーの作成と同じ
トランザクションで書き込み、途中で失敗したらユーザーごと作らない。
The bundled tasks are copied as for any new user, so this adds everything else: a project, chat
history, memos, personal context and a Skill. It writes inside the transaction that creates the
demo user, so a failure part way leaves no user behind.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.context_vault_service import create_fact
from services.repositories.chat_repository import ChatRepository
from services.repositories.memo_repository import insert_memo
from services.repositories.project_repository import ProjectRepository
from services.repositories.user_skill_repository import UserSkillRepository

_PROJECT_NAME = "ポートフォリオサイトの公開"
_PROJECT_INSTRUCTIONS = (
    "個人のポートフォリオサイトを来月公開する準備をしています。"
    "回答は作業の順番が分かるように、チェックリストや表で整理してください。"
)

# (タイトル, [(送信者, 本文), ...]) / (title, [(sender, message), ...])
_PROJECT_ROOM = (
    "公開前のチェックリスト",
    [
        ("user", "ポートフォリオサイトを公開する前に確認しておくことを、優先度の高い順に挙げてください。"),
        (
            "assistant",
            "公開前に確認したい項目を、影響の大きい順に並べました。\n\n"
            "| 優先度 | 項目 | 確認方法 |\n"
            "| --- | --- | --- |\n"
            "| 高 | 連絡先とリンク切れ | すべてのリンクを実際に開く |\n"
            "| 高 | スマホでの表示崩れ | 幅 375px 前後で全ページを見る |\n"
            "| 中 | 表示速度 | Lighthouse で Performance を測る |\n"
            "| 中 | タイトルと説明文 | 共有したときのプレビューを確認する |\n"
            "| 低 | アクセス解析 | 計測タグが動いているか確認する |\n\n"
            "まずは上の2つを片付けると、見た人が困る問題をほぼ防げます。",
        ),
        ("user", "スマホ表示の確認で、見落としやすいところはありますか？"),
        (
            "assistant",
            "見落としやすいのは次の3つです。\n\n"
            "1. **横スクロール**: 長い URL やコード、幅を固定した画像がはみ出していないか。\n"
            "2. **タップのしやすさ**: ボタンやリンクの間隔が狭すぎないか（目安は 44px 四方）。\n"
            "3. **文字の大きさ**: 本文が 16px 未満だと、入力欄で自動ズームが起きる端末があります。\n\n"
            "実機が手元にない場合は、ブラウザーの開発者ツールで端末の幅を切り替えて確認できます。",
        ),
    ],
)

_STANDALONE_ROOM = (
    "お礼メールの下書き",
    [
        ("user", "面談のお礼メールを、丁寧すぎない自然な文面で下書きしてください。"),
        (
            "assistant",
            "件名: 本日の面談のお礼\n\n"
            "〇〇株式会社\n△△様\n\n"
            "本日はお時間をいただき、ありがとうございました。\n"
            "チームの開発の進め方を具体的に伺えて、働く姿をより鮮明に思い描けるようになりました。\n\n"
            "引き続き、どうぞよろしくお願いいたします。\n\n"
            "（氏名）",
        ),
    ],
)

# (タイトル, 本文) / (title, body)
_MEMOS = (
    (
        "公開前のチェックリスト",
        "- [ ] すべてのリンクを開いて確認する\n"
        "- [ ] スマホ幅（375px）で全ページを見る\n"
        "- [ ] Lighthouse で表示速度を測る\n"
        "- [ ] 共有したときのプレビューを確認する\n",
    ),
    (
        "面談で聞きたいこと",
        "## 開発の進め方\n"
        "- コードレビューは何人で、どのくらいの時間で返ってくるか\n"
        "- テストと CI はどこまで整っているか\n\n"
        "## チーム\n"
        "- 入社直後はどんな仕事から始めることが多いか\n",
    ),
)

# (種類, タイトル, 内容, 重要度) / (type, title, content, importance)
_CONTEXT_FACTS = (
    ("preference", "回答の書き方", "結論を先に書き、手順は番号付きのリストにしてほしい。", 80),
    ("project", "ポートフォリオサイト", "Next.js で作った個人サイトを来月公開する予定。", 60),
)

_SKILL_NAME = "議事録の整形"
_SKILL_INSTRUCTIONS = (
    "メモ書きの議事録を渡されたら、次の順に整理して返してください。\n"
    "1. 決まったこと\n"
    "2. 担当者と期限つきの宿題\n"
    "3. 次回までに確認すること\n"
    "元のメモに無い内容は足さないでください。"
)


async def _seed_room(
    chats: ChatRepository,
    user_id: int,
    room: tuple[str, list[tuple[str, str]]],
) -> str:
    title, messages = room
    room_id = str(uuid.uuid4())
    await chats.create_room(room_id, user_id, title)
    parent_id: int | None = None
    for sender, message in messages:
        parent_id = await chats.save_message(room_id, message, sender, parent_id=parent_id)
    return room_id


async def seed_demo_sample_data(user_id: int, *, session: AsyncSession) -> None:
    project = await ProjectRepository(session).create_project(user_id, _PROJECT_NAME, _PROJECT_INSTRUCTIONS)
    chats = ChatRepository(session)
    project_room_id = await _seed_room(chats, user_id, _PROJECT_ROOM)
    await ProjectRepository(session).assign_room_to_project(project_room_id, user_id, int(project["id"]))
    await _seed_room(chats, user_id, _STANDALONE_ROOM)

    for title, body in _MEMOS:
        await insert_memo(user_id, body, title, None, session=session)
    for fact_type, title, content, importance in _CONTEXT_FACTS:
        await create_fact(
            user_id,
            fact_type=fact_type,
            title=title,
            content=content,
            importance=importance,
            session=session,
        )
    await UserSkillRepository(session).create_user_skill(user_id, _SKILL_NAME, _SKILL_INSTRUCTIONS)
