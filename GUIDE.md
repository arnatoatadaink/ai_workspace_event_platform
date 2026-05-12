# AI Workspace Event Platform — 使い方ガイド

## システム全体像

```
Claude CLI ──hooks──▶ POST /ingest ──▶ EventStore (JSONL)
                                            │
                            ┌───────────────┼───────────────┐
                            ▼               ▼               ▼
                       Indexer         Summarizer       UmapRunner
                      (会話DB)         (LM Studio)      (topic座標)
                            │               │               │
                            └───────────────▼───────────────┘
                                     FastAPI (port 8001)
                                           │
                              ┌────────────▼────────────┐
                              │    React WebGUI          │
                              │    (port 5173)           │
                              │  ホーム / イベント /     │
                              │  トピックマップ /        │
                              │  データフロー            │
                              └─────────────────────────┘
```

---

## 前提条件

| ツール | バージョン | 用途 |
|--------|-----------|------|
| Python | 3.13.9+ | バックエンド |
| poetry | 最新 | Python パッケージ管理 |
| Node.js | 24+ (Volta で管理) | フロントエンドビルド |
| pnpm | 11+ | フロントエンドパッケージ管理 |
| LM Studio | 任意 | 会話要約バックエンド（省略可） |

---

## セットアップ

### 1. Python 依存関係

```bash
poetry install
```

### 2. フロントエンド依存関係

```bash
cd web
pnpm install
```

> **pnpm v11 での esbuild エラーが出る場合**
>
> ```
> [ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: esbuild@0.27.7
> ```
>
> 以下の手順で解決します：
> ```bash
> cd web
> rm -f pnpm-lock.yaml
> rm -rf node_modules
> pnpm add vite                 # esbuild が依存として再ダウンロードされる
> pnpm install
> ```
> `web/package.json` の `"pnpm": { "onlyBuiltDependencies": ["esbuild", ...] }` が
> ロックファイルに記録されれば以降は発生しません。

---

## 起動手順

### API サーバー（必須）

```bash
# プロジェクトルートから
uvicorn src.api.main:app --reload --port 8001
```

起動後 `http://localhost:8001/health` → `{"status":"ok"}` で疎通確認。

### フロントエンド開発サーバー

```bash
cd web
pnpm dev
# → http://localhost:5173 で WebGUI 起動
```

---

## WebGUI 各ページの使い方

### ホームページ

| セクション | 内容 |
|-----------|------|
| 接続ステータス | API サーバーへの疎通状態（赤/緑ドット） |
| 接続ソース | Claude CLI 等のプラグイン一覧・バージョン |
| セッション一覧 | 取込/分析/要約の 7 段階パイプライン状態 |

**セッション処理の流れ:**

```
未取込 → [取込] → 取込済 → [分析] → 分析済 → [要約] → 要約済
```

各ボタンは該当状態のセッションにのみ表示されます。

### イベントビュー

1. 左ペインでセッションを選択
2. メインエリアにチャットバブル形式でメッセージを表示
3. 右サイドバー（「Detail ▶」ボタンで開閉）にトピック・会話一覧・生イベント

### トピックマップ

UMAP による topic ベクトルの 2D 散布図。セッション別 / 月別に色分け。

- **セッション絞り込み**: セッション ID を入力
- **時間窓フィルタ**: Since / Until で期間を絞り込み
- **色分け**: session（デフォルト）/ time から選択

### データフロー（静的解析グラフ）

`GET /dataflow/ir` から取得した静的解析結果を ReactFlow でグラフ表示します。

**ノードの色と種別:**

| 色 | 種別 | 意味 |
|----|------|------|
| 青 | Component | React コンポーネント |
| 水色 | Hook | フック呼び出し |
| 薄青 | Fetch | `fetch()` コール |
| オレンジ | Route | FastAPI ルート |
| グレー | Function | Python 関数 |
| 紫 | Pydantic | Pydantic モデル |
| 緑 | Table | DB テーブル |

**エッジの種別:**

| 種別 | 意味 |
|------|------|
| fetches | フロントエンド → API ルート |
| defines | API ルート → Python ハンドラ |
| calls | Python 関数 → Python 関数 |
| queries | Python 関数 → DB テーブル |
| models | API ルート → Pydantic モデル |
| uses_hook | コンポーネント → フック |

**フィルター**: 上部チェックボックスでノード種別の表示/非表示を切り替えられます。

**フロントエンド解析を更新する場合:**

```bash
cd web
pnpm analyze:ir
# → runtime/frontend_analysis.json が更新される
# → API サーバーを再起動するか、ブラウザをリロードで反映
```

---

## 静的解析ツール

### Python 型不一致チェッカー

```bash
poetry run python -m src.analysis.checker src/
```

AST ＋ 呼び出しグラフで関数の引数型とシグネチャ型の不一致を検出します。

### TypeScript/React 静的解析

```bash
cd web

# Rules of Hooks 違反 + 空依存配列 [] 検出（PR 前必須）
pnpm analyze

# データフロー IR 生成（runtime/frontend_analysis.json を更新）
pnpm analyze:ir
```

---

## テスト実行

### Python

```bash
# 増分実行（変更ファイルのみ）
poetry run python -m pytest tests/ -q --tb=short --testmon

# 全件実行
poetry run python -m pytest tests/ -q --tb=short
```

### TypeScript / React

```bash
cd web

# 一発実行（CI 相当）
pnpm test:run

# ウォッチモード
pnpm test

# カバレッジ
pnpm test:coverage

# TypeScript 型チェック
node_modules/.bin/tsc --noEmit
```

---

## Claude CLI フック設定

`.claude/settings.json` に以下が設定済みです。Claude CLI を使用中は自動的にイベントが送信されます。

```json
{
  "hooks": {
    "Stop":       [{ "matcher": "", "hooks": [{ "type": "command", "command": "curl -s -X POST http://localhost:8001/ingest ..." }] }],
    "PreToolUse": [...],
    "PostToolUse": [...]
  }
}
```

API サーバーが停止していても Claude CLI は正常動作します（フックのエラーは無視されます）。

---

## LM Studio 設定（会話要約バックエンド）

| 項目 | 値 |
|------|-----|
| エンドポイント | `http://192.168.2.104:52624/v1` |
| モデル | `gemma-4-31b-it@q6_k` |
| API キー | `lm` |

LM Studio が起動していない場合、要約パイプラインはエラーをスキップして継続します。

---

## ディレクトリ構成（主要パス）

```
├── src/
│   ├── adapters/claude/   Claude CLI フック受信
│   ├── analysis/          静的解析（AST・CGA・DB・Route・IR）
│   ├── api/               FastAPI ルーター
│   ├── replay/            インデクサー・要約・UMAP
│   ├── schemas/           内部イベントスキーマ（Pydantic）
│   └── store/             JSONL イベントストア（追記専用）
├── web/
│   ├── scripts/analysis/  ts-morph 静的解析スクリプト
│   └── src/
│       ├── components/    UI コンポーネント
│       ├── debug/         dev-only ランタイムロガー
│       └── pages/         ページコンポーネント
├── runtime/
│   ├── sessions/          JSONL イベントデータ
│   ├── replay.db          会話インデックス DB
│   └── frontend_analysis.json  フロントエンド IR（pnpm analyze:ir で生成）
└── tests/                 pytest テストスイート
```

---

## よくある問題

### API サーバーが起動しない

```bash
# ポート競合確認
lsof -i :8001
# 依存関係の確認
poetry run python -c "from src.api.main import app; print('OK')"
```

### `Ctrl+C` 後に uvicorn がハングする

```bash
poetry add watchfiles
```

watchfiles が未インストールだとシャットダウン時にハングすることがあります。

### フロントエンドビルドエラー

```bash
cd web
node_modules/.bin/tsc --noEmit  # 型エラーを確認
```

### データフローグラフが空になる

`GET /dataflow/ir` が返す JSON を確認してください：

```bash
curl http://localhost:8001/dataflow/ir | python3 -m json.tool | head -30
```

フロントエンドの解析を含めたい場合は `pnpm analyze:ir` を実行してから API を再起動します。
