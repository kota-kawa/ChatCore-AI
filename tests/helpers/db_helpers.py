# 日本語: テスト環境においてデータベースのトランザクション状態（コミット、ロールバック、クローズなど）を追跡するための擬似的な接続（Connection）クラスです。
# English: A mock database connection class used in testing to track transaction states such as commit, rollback, and close operations.
class TransactionTrackingConnection:
    # 日本語: インスタンス生成時に、追跡フラグの初期化と、指定されたカーソルオブジェクトを保持します。
    # English: Initialize tracking flags and store the provided cursor object during instance creation.
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    # 日本語: クエリ実行用のカーソルオブジェクトを取得します。
    # English: Retrieve the cursor object used for executing database queries.
    def cursor(self):
        return self._cursor

    # 日本語: コミット処理が行われたことを示すフラグを有効にします。
    # English: Mark the connection as committed by updating the tracking flag.
    def commit(self):
        self.committed = True

    # 日本語: ロールバック処理が行われたことを示すフラグを有効にします。
    # English: Mark the connection as rolled back by updating the tracking flag.
    def rollback(self):
        self.rolled_back = True

    # 日本語: 接続がクローズされたことを示すフラグを有効にします。
    # English: Mark the connection as closed by updating the tracking flag.
    def close(self):
        self.closed = True

    # 日本語: コンテキストマネージャの開始時に、自身を返却します。
    # English: Enter the context block, returning the connection instance itself.
    def __enter__(self):
        return self

    # 日本語: コンテキストマネージャの終了時に、接続のクローズ処理を自動的に実行します。
    # English: Exit the context block, automatically closing the connection.
    def __exit__(self, _exc_type, _exc, _tb):
        self.close()
        return False
