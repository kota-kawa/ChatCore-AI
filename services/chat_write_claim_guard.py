"""書き込み完了の申告が承認カードの状態と食い違わないかを検査するモジュール。

Checks that an answer's claim of a finished write matches the approval cards of the turn.

回答本文の文面と、そのターンで作られた承認カードだけを見る純粋関数の集まりで、
LLM もデータベースも呼ばない。食い違いを見つけたときに返す通知文もここが決める。
A set of pure functions that look only at the answer text and the approval cards made in
the turn; nothing here calls an LLM or the database. The notice returned on a mismatch is
decided here as well.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from services.i18n import infer_response_language

from .chat_workspace_tools.profile import PROFILE_SETTINGS_UPDATE_TOOL_NAME
from .chat_workspace_tools.prompts import (
    MY_PROMPT_SAVE_TOOL_NAME,
    MY_SKILL_SAVE_TOOL_NAME,
    PUBLISH_PROMPT_TOOL_NAME,
)

_MEMO_CHANGE_CLAIM_JA = re.compile(
    r"^[ \t]*(?:[^\n。！？]{0,100}メモ[^\n。！？]{0,100}"
    r"(?:追記|追加|修正|編集|作成|保存|更新|登録)しました|"
    r"[^\n。！？]{0,100}メモ[^\n。！？]{0,100}(?:置換|置き換え)ました|追記が完了しました)"
    r"(?=[。！!：:]|$)",
    re.MULTILINE,
)
_MEMO_PASSIVE_CLAIM_JA = re.compile(
    r"^[ \t]*[^\n。！？]{0,100}メモ[^\n。！？]{0,100}(?:"
    r"(?:追記|追加|修正|編集|作成|保存|更新|登録)(?:されました|が完了しました|済みです)|"
    r"置換されました|置き換えられました)"
    r"(?=[。！!：:]|$)",
    re.MULTILINE,
)
_MEMO_PROPOSAL_CLAIM_JA = re.compile(
    r"^[ \t]*[^\n。！？]{0,100}(?:メモ|この変更|その変更|編集案|この追記|この修正)[^\n。！？]{0,100}"
    r"(?:提案を(?:(?:作成|提出)し|出し)(?:ました|ています)|提案(?:しました|しています)|"
    r"(?:承認待ち|保留中)(?:です|となっています))(?=[。！!：:]|$)",
    re.MULTILINE,
)
_MEMO_CHANGE_CLAIM_EN = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?I(?:['’]ve| have) "
    r"(?:created|saved|added|edited|updated|corrected) "
    r"(?:an? |the |your )?(?:draft )?(?:memo|note)\b",
    re.IGNORECASE | re.MULTILINE,
)
_MEMO_PASSIVE_CLAIM_EN = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?(?:(?:Done|Completed)[ \t]*[,—–:-][ \t]*)?"
    r"(?:The|Your|This) "
    r"(?:[A-Za-z0-9][A-Za-z0-9'_-]*[ \t]+){0,8}(?:memo|note) "
    r"(?:(?:has|have) been|was|is(?: now)?) "
    r"(?:created|saved|added to|edited|updated|corrected|replaced)\b",
    re.IGNORECASE | re.MULTILINE,
)
_MEMO_PROPOSAL_CLAIM_EN = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?I(?:(?:['’]ve| have) proposed| propose) "
    r"(?:creating|adding to|editing|updating|correcting|saving) "
    r"(?:an? |the |your )?(?:memo|note)\b",
    re.IGNORECASE | re.MULTILINE,
)
_MEMO_PENDING_CLAIM_EN = re.compile(
    r"^[ \t]*(?:It(?:['’]s| is) waiting for your approval|"
    r"(?:(?:The|Your|This) )?(?:memo|note)(?:[ \t]+(?:update|change|edit|proposal))? "
    r"is(?: now)? (?:waiting for (?:your )?approval|pending approval|awaiting (?:your )?approval)|"
    r"(?:The|Your|This) (?:change|proposal) is waiting for your approval)"
    r"(?=[.!?]|$)",
    re.IGNORECASE | re.MULTILINE,
)


# メモ以外の書き込みツール（プロフィール・Task・公開投稿・Skill）の完了申告。プロンプトやタスクは会話の
# 下書きとしても普通に「作成しました」と書かれるため、同じ対象のカードがこのターンにあり、どれも実行済み
# でないときだけ食い違いとみなす。カードの無い回答は下書きと区別できないので判定しない。
# Completion claims for the non-memo write tools (profile, Task, public post, Skill). Prompts and
# tasks are also drafted in ordinary chat ("I've created a prompt:"), so a claim counts as a mismatch
# only when this turn has a card for the same target and none of them was executed. An answer with no
# such card cannot be told apart from a draft and is not judged.
_WRITE_TARGET_TOOLS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (
        re.compile(
            r"プロフィール|表示名|自己紹介|言語設定|表示設定|テーマ|profile|display name|"
            r"preferred language|\blocale\b|\bbio\b|\btheme\b",
            re.IGNORECASE,
        ),
        frozenset({PROFILE_SETTINGS_UPDATE_TOOL_NAME}),
    ),
    (re.compile(r"タスク|\btask\b", re.IGNORECASE), frozenset({MY_PROMPT_SAVE_TOOL_NAME})),
    (
        re.compile(r"プロンプト|\bprompt\b", re.IGNORECASE),
        frozenset({MY_PROMPT_SAVE_TOOL_NAME, PUBLISH_PROMPT_TOOL_NAME}),
    ),
    (re.compile(r"スキル|skill", re.IGNORECASE), frozenset({MY_SKILL_SAVE_TOOL_NAME})),
)
_WRITE_CLAIM_JA = re.compile(
    r"^[ \t]*(?:[-*・][ \t]*)?[^\n。！？]{0,100}?"
    r"(?<![非未])(?P<action_jp>更新|変更|保存|作成|登録|公開|投稿|追加|編集|設定)"
    r"(?:しました|いたしました|されました|が完了しました|済みです)"
    r"(?=[。！？!：:*、,;；]|が(?:[、, \t]|$)|$)",
    re.MULTILINE,
)
_WRITE_CLAIM_EN = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?(?:(?:Done|Completed)[ \t]*[,—–:-][ \t]*)?"
    r"(?:I(?:['’]ve| have)? (?P<active_action>updated|changed|saved|created|published|posted|added|edited|set)\b"
    r"|(?:The|Your|This|Task|Prompt|Skill) (?:[A-Za-z0-9][A-Za-z0-9'_-]*[ \t]+){0,8}"
    r"(?:(?:has|have) been|was|is(?: now)?)(?: successfully)? "
    r"(?P<passive_action>updated|changed|saved|created|published|posted|added|edited|set)\b)",
    re.IGNORECASE | re.MULTILINE,
)
_COMPOUND_PUBLISH_CLAIM_JA = re.compile(
    r"(?:保存|更新|変更|作成|登録|追加|編集)(?:し(?:て)?|した?(?:後|あと|のち)に|してから)"
    r"[ \t、,]*(?:その後に?|から)?[ \t]*"
    r"(?:公開|投稿)(?:しました|いたしました|されました|済み(?:です)?)"
)
_COMPOUND_PUBLISH_CLAIM_EN = re.compile(
    r"\b(?:saved|updated|changed|created|added|edited)\b[^.!?\n]{0,100}?"
    r"\b(?:and(?:[ \t]+then)?|then)[ \t]+(?:have[ \t]+)?(?:published|posted)\b",
    re.IGNORECASE,
)
_WRITE_DRAFT_CONTEXT = re.compile(
    r"\b(?:task|prompt) list\b|タスクリスト|タスク一覧|下書き|\bdraft\b",
    re.IGNORECASE,
)
_LATER_WRITE_CLAIM_EN = re.compile(
    r"\b(?:and|then|but|also)[ \t]+(?:(?:(?:I(?:['’]ve| have)?|the|your|this)[ \t]+)?"
    r"(?P<active_action>updated|changed|saved|created|published|posted|added|edited|set)\b"
    r"|(?:The|Your|This|Task|Prompt|Skill) (?:[A-Za-z0-9][A-Za-z0-9'_-]*[ \t]+){0,8}"
    r"(?:(?:has|have) been|was|is(?: now)?)(?: successfully)? "
    r"(?P<passive_action>updated|changed|saved|created|published|posted|added|edited|set)\b)",
    re.IGNORECASE,
)
_WRITE_CLAIM_CONTRAST = re.compile(
    r"\b(?:but|however|yet|although|whereas)\b|(?:ですが|けれども|ものの|一方で)|が(?=[、, \t])",
    re.IGNORECASE,
)
_WRITE_CLAIM_STATUS_AND = re.compile(
    r"[,;]?[ \t]+\band[ \t]+(?=[^.!?\n]{0,80}\b(?:is|are|remains?)"
    r"[ \t]+(?:still[ \t]+)?(?:awaiting|waiting|pending)\b"
    r"|[^.!?\n]{0,80}\b(?:has|have|was|were)[ \t]+not[ \t]+(?:yet[ \t]+)?"
    r"(?:been[ \t]+)?(?:saved|updated|changed|created|published|posted|added|edited|set)\b)",
    re.IGNORECASE,
)
_LATER_WRITE_CLAIM_JA = re.compile(
    r"(?:、|,|また|そして|その後)[^。！？\n]{0,60}?"
    r"(?<![非未])(?P<action_jp>更新|変更|保存|作成|登録|公開|投稿|追加|編集|設定)"
    r"(?:しました|いたしました|されました|が完了しました|済みです)"
)


def _is_non_memo_publish_claim(claim: re.Match[str]) -> bool:
    action = claim.groupdict().get("action_jp") or claim.groupdict().get("active_action") or claim.groupdict().get("passive_action")
    return action in {"公開", "投稿"} or (action or "").casefold() in {"published", "posted"}


def _is_compound_non_memo_publish_claim(action_statement: str) -> bool:
    return bool(_COMPOUND_PUBLISH_CLAIM_JA.search(action_statement) or _COMPOUND_PUBLISH_CLAIM_EN.search(action_statement))


_PROFILE_FIELD_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("display_name", re.compile(r"表示名|display name", re.IGNORECASE)),
    ("bio", re.compile(r"自己紹介|\bbio\b", re.IGNORECASE)),
    ("llm_profile_context", re.compile(r"プロフィール(?:の)?文脈|profile context", re.IGNORECASE)),
    ("preferred_locale", re.compile(r"言語設定|preferred language|locale", re.IGNORECASE)),
    ("theme", re.compile(r"テーマ|theme", re.IGNORECASE)),
)
_WRITE_QUOTED_VALUE = re.compile(
    r"「([^」]*)」|『([^』]*)』|\"([^\"]*)\"|“([^”]*)”|`([^`]*)`|(?<!\w)'([^']*)'(?!\w)"
)


def _write_card_aliases(card: dict[str, Any]) -> tuple[str, ...]:
    preview = card.get("preview")
    if not isinstance(preview, dict) or preview.get("kind") != card.get("tool"):
        return ()
    tool = card.get("tool")
    if tool == PROFILE_SETTINGS_UPDATE_TOOL_NAME:
        keys = ("display_name", "bio", "llm_profile_context", "preferred_locale", "theme")
    elif tool == MY_PROMPT_SAVE_TOOL_NAME:
        keys = ("title", "current_title")
    elif tool == PUBLISH_PROMPT_TOOL_NAME:
        keys = ("title",)
    elif tool == MY_SKILL_SAVE_TOOL_NAME:
        keys = ("name", "current_name")
    else:
        return ()
    return tuple(
        value.strip()
        for key in keys
        if isinstance((value := preview.get(key)), str) and value.strip()
    )


def _text_mentions_write_alias(value: str, text: str) -> bool:
    quoted_values = [
        next((value for value in match.groups() if value is not None), "")
        for match in _WRITE_QUOTED_VALUE.finditer(text)
    ]
    if quoted_values:
        return any(candidate.strip().casefold() == value.casefold() for candidate in quoted_values)
    return bool(re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.IGNORECASE))


def _write_card_matches_target(card: dict[str, Any], text: str) -> bool:
    return bool(_write_card_target_keys(card, text))


def _write_card_target_keys(card: dict[str, Any], text: str) -> tuple[tuple[str, str, str], ...]:
    tool = card.get("tool")
    preview = card.get("preview")
    if not isinstance(preview, dict) or preview.get("kind") != tool:
        return ()
    keys = [
        (str(tool), "alias", alias.casefold())
        for alias in _write_card_aliases(card)
        if _text_mentions_write_alias(alias, text)
    ]
    if tool == PROFILE_SETTINGS_UPDATE_TOOL_NAME:
        keys.extend(
            (str(tool), "field", field)
            for field, marker in _PROFILE_FIELD_MARKERS
            if field in preview and marker.search(text)
        )
    return tuple(keys)


def _write_claim_action(claim: re.Match[str]) -> str:
    return (
        claim.groupdict().get("action_jp")
        or claim.groupdict().get("active_action")
        or claim.groupdict().get("passive_action")
        or ""
    ).casefold()


def _is_direct_target_completion(statement: str, card: dict[str, Any], claim: re.Match[str], compound: bool) -> bool:
    tool = card.get("tool")
    action = _write_claim_action(claim)
    if _WRITE_DRAFT_CONTEXT.search(statement):
        return False
    if tool == PUBLISH_PROMPT_TOOL_NAME:
        return bool(
            re.search(r"プロンプト|\bprompt\b", statement, re.IGNORECASE)
            and (compound or action in {"公開", "投稿", "published", "posted"})
        )
    if tool == MY_PROMPT_SAVE_TOOL_NAME:
        target = re.search(r"\btask\b|タスク", statement, re.IGNORECASE)
        if target:
            return not compound and action in {"保存", "更新", "変更", "編集", "saved", "updated", "changed", "edited"}
        return bool(
            re.search(r"プロンプト|\bprompt\b", statement, re.IGNORECASE)
            and not compound
            and action in {"保存", "更新", "変更", "編集", "saved", "updated", "changed", "edited"}
        )
    if tool == MY_SKILL_SAVE_TOOL_NAME:
        return bool(
            re.search(r"スキル|\bskill\b", statement, re.IGNORECASE)
            and action in {"作成", "登録", "保存", "編集", "更新", "created", "saved", "edited", "updated"}
        )
    if tool == PROFILE_SETTINGS_UPDATE_TOOL_NAME:
        return bool(
            (
                re.search(r"プロフィール|profile", statement, re.IGNORECASE)
                or any(marker.search(statement) for _, marker in _PROFILE_FIELD_MARKERS)
            )
            and action in {"更新", "変更", "編集", "設定", "保存", "updated", "changed", "edited", "set", "saved"}
        )
    return False


def _matching_non_memo_write_cards(
    cards: Sequence[dict[str, Any]], statement: str, latest_user_message: str, claim: re.Match[str], compound: bool
) -> list[dict[str, Any]]:
    if _WRITE_DRAFT_CONTEXT.search(statement):
        return []
    explicit_matches = [card for card in cards if _write_card_matches_target(card, statement)]
    if explicit_matches:
        return explicit_matches
    # Without a name in the answer, only bind an unambiguous direct completion claim
    # to the unique target named by the latest request. Draft-like language stays alone.
    if not cards or any(
        next((value for value in match.groups() if value is not None), "")
        for match in _WRITE_QUOTED_VALUE.finditer(statement)
    ):
        return []
    requested = [
        card for card in cards
        if _write_card_target_keys(card, latest_user_message)
        and _is_direct_target_completion(statement, card, claim, compound)
    ]
    return requested if len(requested) == 1 else []


def _is_approval_artifact_creation(statement: str, claim: re.Match[str]) -> bool:
    action = claim.groupdict().get("action_jp") or claim.groupdict().get("active_action") or claim.groupdict().get("passive_action")
    if action in {"作成", "追加", "登録"}:
        before = statement[: claim.start("action_jp")]
        return bool(
            re.search(
                r"(?:提案|承認)?カード(?:[^。！？]{0,10})?(?:を|が)?[ \t]*$"
                r"|提案(?:[^。！？]{0,10})?(?:を|が)?[ \t]*$",
                before,
            )
        )
    if action and action.casefold() in {"created", "added"}:
        start = claim.start("active_action") if claim.group("active_action") else claim.start("passive_action")
        end = claim.end("active_action") if claim.group("active_action") else claim.end("passive_action")
        before = statement[max(0, start - 40) : start]
        after = statement[end : end + 40]
        return bool(
            re.search(r"(?:approval[ \t]+)?(?:card|proposal)(?:[ \t]+(?:was|has been|is))?[ \t]+$", before, re.IGNORECASE)
            or re.match(r"[ \t]+(?:an?[ \t]+)?(?:approval[ \t]+)?(?:card|proposal)\b", after, re.IGNORECASE)
        )
    return False


def _claim_after_approval_artifact(statement: str, claim: re.Match[str]) -> re.Match[str] | None:
    if claim.groupdict().get("action_jp"):
        start = claim.end("action_jp")
        candidates = [match for match in (_LATER_WRITE_CLAIM_JA.search(statement, start),) if match]
    else:
        start = claim.end("active_action") if claim.group("active_action") else claim.end("passive_action")
        candidates = [match for match in (_LATER_WRITE_CLAIM_EN.search(statement, start),) if match]
    return min(candidates, key=lambda match: match.start()) if candidates else None


def _split_write_claim_contrasts(statement: str) -> tuple[str, ...]:
    separators = list(_WRITE_CLAIM_CONTRAST.finditer(statement))
    separators.extend(
        match
        for match in _WRITE_CLAIM_STATUS_AND.finditer(statement)
        if _LATER_WRITE_CLAIM_EN.match(statement[match.start() :]) is None
    )
    separators.sort(key=lambda match: match.start())
    parts: list[str] = []
    start = 0
    for separator in separators:
        parts.append(statement[start : separator.start()])
        start = separator.end()
    parts.append(statement[start:])
    clauses = tuple(part.strip(" \t、,") for part in parts)
    return tuple(clause for clause in clauses if clause)


# 完了を申告した対象ごとに、このターンのカードがそれを裏付けないか。裏付けのない対象が1つでもあれば
# True、判定の材料が無ければ False。
# Whether any claimed target has cards in this turn but none executed; False when there is nothing
# to judge the claim against.
def _non_memo_write_claim_contradicted(
    statement: str, action_statement: str, latest_user_message: str, approval_cards: Sequence[dict[str, Any]]
) -> bool:
    if not approval_cards:
        return False
    for clause in _split_write_claim_contrasts(statement):
        claim = _WRITE_CLAIM_JA.match(clause) or _WRITE_CLAIM_EN.match(clause)
        if claim is None:
            continue
        claim_clause = clause
        if _is_approval_artifact_creation(clause, claim):
            claim = _claim_after_approval_artifact(clause, claim)
            if claim is None:
                continue
            # 後続が「それを保存した」のような代名詞でも、直前の承認カード作成に付いた
            # 対象名を照合文脈として残す。
            # Retain the preceding target when the later claim refers to it with a pronoun.
            claim_clause = clause
        for pattern, tools in _WRITE_TARGET_TOOLS:
            if not pattern.search(claim_clause):
                continue
            compound = False
            if PUBLISH_PROMPT_TOOL_NAME in tools:
                compound = _is_compound_non_memo_publish_claim(action_statement)
                if compound:
                    tools = frozenset({MY_PROMPT_SAVE_TOOL_NAME, PUBLISH_PROMPT_TOOL_NAME})
                else:
                    tool = PUBLISH_PROMPT_TOOL_NAME if _is_non_memo_publish_claim(claim) else MY_PROMPT_SAVE_TOOL_NAME
                    tools = frozenset({tool})
            cards = [card for card in approval_cards if card.get("tool") in tools]
            cards = _matching_non_memo_write_cards(cards, claim_clause, latest_user_message, claim, compound)
            target_keys = {key for card in cards for key in _write_card_target_keys(card, claim_clause)}
            if cards and not target_keys and not any(card.get("status") == "succeeded" for card in cards):
                return True
            for target_key in target_keys:
                target_cards = [card for card in cards if target_key in _write_card_target_keys(card, claim_clause)]
                if target_cards and not any(card.get("status") == "succeeded" for card in target_cards):
                    return True
    return False


def _matching_memo_claim_card(
    statement: str,
    latest_user_message: str,
    approval_cards: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    # A single card with a visible target is required; another card's status cannot
    # substantiate a claim about this memo.
    if len(approval_cards) != 1:
        return None
    card = approval_cards[0]
    preview = card.get("preview")
    if not isinstance(preview, dict) or preview.get("kind") != card.get("tool"):
        return None
    claim = re.sub(r'「[^」]*」|『[^』]*』|"[^"]*"|“[^”]*”|`[^`]*`', "", statement).casefold()
    if re.search(r"追記|追加|\b(?:added to|adding to)\b", claim):
        expected_tool = "memo_append"
    elif re.search(r"修正|編集|\b(?:edited|editing|corrected|correcting)\b", claim):
        expected_tool = "memo_edit"
    elif re.search(r"作成|\b(?:created|creating)\b", claim):
        expected_tool = "memo_create"
    else:
        expected_tool = None
    if expected_tool is not None and card.get("tool") != expected_tool:
        return None
    title = preview.get("title") if card.get("tool") == "memo_create" else preview.get("memo_title")
    if not isinstance(title, str) or not title.strip():
        return None
    title = title.strip()
    statement_folded = statement.casefold()
    title_folded = title.casefold()
    if title_folded in statement_folded:
        return card
    # Generic statements can refer to the sole requested memo. A different named
    # memo, or a missing target in the request, leaves the claim unverified.
    if title_folded not in latest_user_message.casefold():
        return None
    named_memos = re.findall(r"[^\s、。！？「」『』：:]{2,50}メモ", statement)
    if any(name not in {"新しいメモ", "このメモ", "そのメモ", "対象メモ"} for name in named_memos):
        return None
    if re.search(r"\b(?:the|your|this) [A-Za-z0-9][A-Za-z0-9' _-]{0,48} (?:memo|note)\b", statement, re.IGNORECASE):
        return None
    if re.search(r"\bcalled\b", statement, re.IGNORECASE):
        return None
    return card


def _unconfirmed_write_claim_fallback(
    text: str,
    latest_user_message: str,
    approval_cards: Sequence[dict[str, Any]] = (),
) -> str | None:
    """Replace memo write claims, and non-memo write claims its cards contradict, with a notice."""
    # Quoted examples and code are data, not claims made by the assistant.
    prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for line in prose.splitlines():
        # 引用した説明は判定せず、引用した題名はカードとの照合に残す。
        # Mask quoted claims while preserving offsets to match quoted memo titles to cards.
        masked = re.sub(
            _WRITE_QUOTED_VALUE,
            lambda match: " " * len(match.group()),
            line,
        )
        statements = list(re.finditer(r".+?(?:[。！？!?]|\.[ \t]+|$)", masked))
        for index, match in enumerate(statements):
            statement = match.group()
            lead = statement.lstrip()
            if lead.startswith((">", "'", "もし", "仮に", "例えば", "例：", "例:", "If ", "When ")):
                continue
            # A quoted status can be followed by an explanatory 「と表示」 even without quotes.
            if index + 1 < len(statements) and statements[index + 1].group().lstrip().startswith("と表示"):
                continue
            proposal = _MEMO_PROPOSAL_CLAIM_JA.match(statement) or _MEMO_PROPOSAL_CLAIM_EN.match(statement)
            pending = _MEMO_PENDING_CLAIM_EN.match(statement) or (
                proposal and any(status in proposal.group() for status in ("承認待ち", "保留中"))
            )
            completed = (
                _MEMO_CHANGE_CLAIM_JA.match(statement)
                or _MEMO_CHANGE_CLAIM_EN.match(statement)
                or _MEMO_PASSIVE_CLAIM_JA.match(statement)
                or _MEMO_PASSIVE_CLAIM_EN.match(statement)
            )
            # 「その変更は承認待ちです」のようにメモと名指ししない文は、メモのカードが無いターンでは
            # 他の対象（Skill など）のカードの説明なので、メモの判定にかけない。
            # A statement that never names a memo ("the change is awaiting approval") describes another
            # target's card (a Skill, say) when the turn has cards but none for memos.
            if (
                (proposal or pending)
                and approval_cards
                and not any(str(card.get("tool") or "").startswith("memo_") for card in approval_cards)
                and not re.search(r"メモ|\b(?:memo|note)\b", statement, re.IGNORECASE)
            ):
                continue
            if not (proposal or pending or completed):
                original_statement = line[match.start() : match.end()]
                if _non_memo_write_claim_contradicted(
                    original_statement, match.group(), latest_user_message, approval_cards
                ):
                    return _unconfirmed_write_notice(latest_user_message, approval_cards, memo=False)
                continue
            card = _matching_memo_claim_card(line[match.start():match.end()], latest_user_message, approval_cards)
            status = card.get("status") if card else None
            if pending and status == "pending":
                continue
            if proposal and not pending and status in {"pending", "succeeded"}:
                continue
            if completed and status == "succeeded" and not proposal:
                continue
            return _unconfirmed_write_notice(latest_user_message, approval_cards, memo=True)
    return None


def _unconfirmed_write_notice(latest_user_message: str, approval_cards: Sequence[dict[str, Any]], *, memo: bool) -> str:
    # メモ以外はカードがあるときだけ判定するので、「カードも作成されていない」文面はメモだけが使う。
    # Non-memo claims are judged only with cards present, so only memo uses the "no card" wording.
    if infer_response_language(latest_user_message) == "en":
        if approval_cards or not memo:
            return "This description does not match the approval card status. Please check the card."
        return "The memo change was not submitted, and no approval card was created. Please try again."
    if approval_cards or not memo:
        return "この説明と承認カードの状態が一致しません。承認カードを確認してください。"
    return "メモの変更は送信されておらず、承認カードも作成されていません。もう一度お試しください。"
