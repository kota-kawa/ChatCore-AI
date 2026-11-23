"""一時ファイル経由でバイト列を原子的に書き込む共通関数。

Shared helper that writes bytes atomically through a temporary file.
"""

from __future__ import annotations

import os
import tempfile


def atomic_write_bytes(destination: str, content: bytes, *, temporary_prefix: str) -> None:
    """一時ファイルへ書いてから置き換え、読み手が書きかけのファイルを見ないようにする。

    `temporary_prefix` は同じディレクトリに作る一時ファイル名の接頭辞で、呼び出し元の機能ごとに変える。

    Write atomically so readers never observe a partially written file.
    `temporary_prefix` names the temporary file created beside the destination and differs per caller.
    """
    fd, temporary_path = tempfile.mkstemp(prefix=temporary_prefix, dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary_path, destination)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise
