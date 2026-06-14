# 日本語: TransactionTrackingConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to TransactionTrackingConnection.
class TransactionTrackingConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self):
        return self._cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.committed = True

    # 日本語: rollback に関する処理の入口です。
    # English: Entry point for logic related to rollback.
    def rollback(self):
        self.rolled_back = True

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True

    # 日本語: コンテキスト開始時に必要な準備を行います。
    # English: Prepare the object when entering the context.
    def __enter__(self):
        return self

    # 日本語: コンテキスト終了時の後片付けを行います。
    # English: Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
