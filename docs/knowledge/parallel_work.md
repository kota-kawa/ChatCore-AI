# 並行作業（git worktree）の運用手順

サブエージェントと worktree をいつ使うかの判断基準は `../../AGENTS.md` の「エージェントの作業ルール」にあります。ここには、worktree を分けた後に守る運用手順だけを置きます。

## 資源と並行数

- 並行数の上限は worktree の本数ではなく、担当ファイルが重複しないことで決まります。同じファイルを編集する予定の作業は worktree を増やしても解決せず、片方を待たせます。
- 重複が無ければ機械資源は制約になりません。worktree 1 本あたり数百 MB で、`.git` は worktree 間で共有されます。
- 1 worktree = 1 ブランチ = 1 PR です。同時にオープンする PR の本数に上限は設けませんが、1 本マージするたびに残りを `main` へリベースする手間が増えるため、本数を増やす前に重複の無い単位へ切れているかを確認します。

## worktree 間で共有される資源

- DB／Redis／ポートは worktree 間で共有されます。alembic migration の適用や `docker-compose up` を伴う作業は同時に 1 つだけにしてください。
- `.env` は git 管理外のため、新規 worktree では `python3 app.py` を起動できません。起動が必要な作業は共有ツリーで行います。

## 依存のある作業

- 依存のある作業は同時に走らせず、先行側が終わってから始めます。
- 先行 PR の上に積んだ PR（base が先行 PR のブランチ）では、本文の `Closes #番号` は働きません。GitHub は既定ブランチへのマージでしか issue を閉じないため、先行 PR のマージ後に base を `main` へ切り替えてからマージし、issue が閉じたかを確認します。先行 PR へ追加コミットしたら、積んだ側のブランチを `git rebase <先行ブランチ>` で載せ直してから push します。
- 並列作業中に他の作業への依存が判明したら、その場で止めてユーザーに報告します。担当 worktree の外を触って解決しようとしないでください。

## worktree でフロントエンドを検証する

- `frontend/node_modules` を共有ツリーのものへシンボリックリンクします。

  ```sh
  ln -s <共有ツリー>/frontend/node_modules <worktree>/frontend/node_modules
  ```

- これで `npm run typecheck`／`npm run lint`／`npm run test`（`test:logic` と `test:components` を順に実行）が動きます。
- リンク先の共有ツリーを壊すため、worktree では `npm install`／`npm ci`／`npm update` を実行しないでください。

## 作業終了後の worktree 削除

- 使い終わった作業用 worktree は残さず削除します。必要な成果のコミット・push・PR 作成が済み、追加の検証・修正で使う予定がなくなった時点が削除のタイミングです。PR が未マージでも、この条件を満たしていれば削除します。
- 削除前に対象 worktree の `git status --short --untracked-files=all` を確認し、未コミット・未追跡の必要なファイルが残っていないことと、必要なコミットがリモートへ push 済みであることを確認します。git 管理外・ignore 対象のファイルにも必要なものがあれば退避し、未保存の成果がある場合は削除を保留してユーザーへ報告してください。
- 対象 worktree を使っている自分の開発サーバー・テストプロセス・サブエージェントを終了させ、共有ツリーなど対象外のディレクトリへ移動してから `git worktree remove <worktree>` を実行します。`rm -rf` や `git worktree remove --force` で変更を強制的に破棄してはいけません。
- 削除後は `git worktree list` で対象が登録から消えたことを確認します。worktree の削除とブランチの削除は別の操作です。PR が参照しているブランチは残してください。
- この手順で削除するのは自分の担当作業で使い終わった worktree だけです。共有ツリーや他の担当者の worktree は無断で削除しないでください。
