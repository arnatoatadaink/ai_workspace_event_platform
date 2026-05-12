# TODO — AI Workspace Event Platform

> 凡例: ✅ 完了 / ⬜ 未着手 / ⏸ 保留
> 設計書: `ai_workspace_event_platform_plan_v1_2.md`

---

## 完了

### プロジェクト基盤
- ✅ 設計書 v1.1 / v1.2 作成
- ✅ `CLAUDE.md` / `CLAUDE_USER.md` 作成
- ✅ `.claude/rules/` 整備（python-strict / testing / event-schema / commit / for-user-localization）
- ✅ `forUser/rules/` 日本語対応ファイル作成
- ✅ `.claude/settings.json` をこのプロジェクト用に更新

### STEP 1 — コア層
- ✅ `src/schemas/internal_event_v1.py` — InternalEvent / MessageEvent / ToolCallEvent / ToolResultEvent / StopEvent / ApprovalEvent / SummaryUpdateEvent / TopicExtractionEvent / `parse_event()`
- ✅ `schemas/claude/stop_hook_v1.schema.json` / `pre_tool_use_v1.schema.json` / `post_tool_use_v1.schema.json`
- ✅ `src/store/event_store.py` — append-only JSONL、chunk rotation（デフォルト10,000 events/chunk）
- ✅ `src/adapters/base.py` — `AdapterPlugin` interface
- ✅ `src/adapters/claude/adapter.py` — Stop / PreToolUse / PostToolUse 対応
- ✅ `tests/` — 30テスト全GREEN（test_internal_event_v1 / test_event_store / test_claude_adapter）

---

## 次にやること（STEP 2）

### Replay初期化処理（重い処理・v1.2設計 §1）

#### 1-1: 会話単位インデックスDB
- ✅ `src/replay/db.py` — SQLite初期化・`conversations`テーブル定義・カーソルページングクエリ・`get_last_indexed_event()`（delta検出用）
- ✅ `src/replay/indexer.py` — chunkから会話境界を検出してDBに索引保存
- ✅ 最新会話から遡れるクエリ実装（`ORDER BY created_at DESC` + カーソル）

#### 1-2: 会話単位の要約・topic生成
- ✅ `src/replay/db.py` に `conversation_summaries` テーブル追加（insert_summary / get_summary / get_unsummarized_conversations）
- ✅ `src/replay/summarizer.py` — SummarizerBackend Protocol / OpenAICompatBackend（LM Studio + Gemma 4-31b）/ ClaudeBackend / summarize_conversation()

#### 1-n: Snapshot・差分処理
- ✅ `src/replay/snapshot_models.py` — EventRange / ContextLength / TopicSummary / SnapshotMetadata Pydantic モデル
- ✅ `src/replay/snapshot_store.py` — SnapshotStore（DBインデックス + JSONファイル永続化）
- ✅ `src/replay/snapshot.py` — `detect_unprocessed_chunks()`（chunk末尾逆引き差分）/ `run_incremental_update()`（orchestrator）
- ✅ `src/replay/indexer.py` に `chunks` / `global_idx_start` パラメータ追加（chunk単位スキップ対応）

### FastAPI（STEP 2後半）
- ✅ `src/api/main.py` — FastAPIアプリ初期化、AdapterPlugin読み込み（lifespan）
- ✅ `POST /ingest` — Claude CLI hookペイロード受信・変換・保存
- ✅ `GET /sessions` — セッション一覧（event_count付き）
- ✅ `GET /events` — イベント一覧（session_id指定、limit+offsetページネーション）
- ✅ `GET /topics` — scope（conversation/session/global）・with_counts・within_days/hours/minutes 対応
- ✅ `WS /stream` — WebSocket event stream（session_id指定、1秒ポーリング）
- ✅ `tests/test_api.py` — 15テスト全GREEN（scope/time filter/with_counts を網羅）

### Summary・Topic Pipeline（STEP 2後半）
- ✅ `src/replay/pipeline.py` — SummaryTopicPipeline（run_once / run_loop / stop）全セッション対応・エラー分離
- ✅ `src/api/main.py` に SnapshotStore + SummaryTopicPipeline をlifespanバックグラウンドタスクとして統合

---

## バックログ

### STEP 3 — GUI・Topic追従

#### GUI基盤
- ✅ React プロジェクト初期化（Vite + React + TypeScript、`web/`）
- ✅ セッション一覧UI（`SessionList.tsx`）
- ✅ メッセージ詳細UI（`MessageDetail.tsx`）
- ✅ 会話・要約ペイン（`ConversationPane.tsx`）
- ✅ ホームページ（`HomePage.tsx`）— 接続ソース・プラグイン管理・最近のセッション
- ✅ 2ページ構成（ホーム / イベントビュー）ナビゲーション
- ✅ `GET /plugins` + `POST /plugins/{name}/check-update` API
- ✅ `src/api/plugin_catalog.py` — 静的プラグインカタログ（claude/webchat/discord/gemini）
- ✅ `AdapterPlugin` に `version` / `description` プロパティ追加
- ✅ `CORSMiddleware` 追加（`localhost` 任意ポート対応）
- ✅ API ポートを 8001 に統一（MED との競合回避）

#### GUI参照処理（v1.2設計 §2）
- ✅ **2-1** `GET /sessions/{id}/conversations` — カーソルページングAPI（LEFT JOIN、未サマリー会話も含む）
- ✅ **2-1** 最新会話からのロード・遡り表示（before_conversation_id カーソル）
- ✅ **2-2** Topic追従API（移動平均、window=N会話）`GET /sessions/{id}/topics/active`
- ✅ **2-2** アクティブtopic可視化UI（`TopicPane.tsx`、スコアバー表示）

#### Claude CLI 接続・セッション検出
- ✅ `.claude/settings.json` — Stop / PreToolUse / PostToolUse hook を `/ingest` にPOST送信するよう追加
- ✅ `GET /health` — API疎通確認エンドポイント
- ✅ `GET /claude/scan-sessions` — `~/.claude/projects/<slug>/` をスキャンしてセッション一覧返却
- ✅ `HomePage.tsx` — API接続ステータスインジケーター追加
- ✅ `HomePage.tsx` — Claude CLIセッション一覧（ログから）セクション追加（取込済/未取込バッジ付き）

#### GUI バグ修正（2026-05-10）
- ✅ `TopicPane.tsx` — `topics.map is not a function` 修正（APIレスポンス `{ active_topics, window }` から `.active_topics` を取り出すよう修正）
- ✅ `api.ts` `ActiveTopicItem` — フィールド名 `score` → `weight`、`trend` 追加、`ActiveTopicsResponse` 型追加
- ✅ `TopicPane.tsx` — `trend` インジケーター表示追加（NEW / ↑ / ─ / ↓）、window会話数表示追加
- ✅ `ConversationPane.tsx` — `Cannot read properties of undefined (reading 'map')` 修正（APIはプレーン配列を返すため `fetchConversations` 内で `{ items, next_cursor }` に変換）
- ✅ `api.ts` `ConversationItem` — フィールド名を API に合わせて修正（`started_at`→`created_at`、`summary`→`summary_short`、`message_count` 等追加）
- ✅ `MessageDetail.tsx` — "Invalid Date" 修正（`ev.created_at` → `ev.timestamp`）
- ✅ `MessageDetail.tsx` — `approval_required` ラベル未変換を修正（`EVENT_LABEL` キー修正）
- ✅ `MessageDetail.tsx` — `ev.payload` 参照エラー修正（イベントはフラット構造のためベースフィールドを除いた残りを表示）

#### 既知の制約（対応待ち）
- ✅ `message_count` が常に 0 — `src/adapters/claude/transcript.py` 新設。Stopフック時に `transcript_path` を読み取り `MessageEvent` を emit（カーソルで重複防止・サイドチェーン除外・移行ガード付き）
- ✅ STOPフックが発火しなかったセッション（強制終了・中断）は会話レコードが作られず「会話なし」になる — `is_pending=True` の合成エントリを先頭に表示（amber左ボーダー・「進行中」バッジ）

#### チャットビュー追加（2026-05-10）
- ✅ `ChatPane.tsx` — user / assistant メッセージをチャットバブル形式で表示（右寄せ / 左寄せ）
- ✅ インフィニットスクロール — 上スクロールで過去メッセージを PAGE_SIZE=50 件ずつ追加読み込み
- ✅ LocalStorage によるセッション・スクロール位置・表示件数の記憶（`awep:lastSession` / `awep:chat:scrollTop:{id}` / `awep:chat:displayCount:{id}`）
- ✅ Detail サイドバー（`DetailSidebar.tsx`）— 右側に TopicPane / ConversationPane / 生イベントを統合、"Detail ▶" トグルで開閉、状態は `awep:sidebarOpen` に保存
- ✅ レイアウト変更 — 2×2 グリッド → flex 3カラム（SessionList | ChatPane | DetailSidebar）
- ⬜ TODO: Stop フックから `transcript_path` が届かないため `event_type: "message"` がストアに存在しない。ChatPane は空状態でTODOメッセージを表示中。transcript_path 疎通を確認すること。

#### セッション単位要約API（2026-05-10）
- ✅ `POST /sessions/{session_id}/summarize` — セッション内の未要約会話をまとめて要約（`force=true` で全会話再要約）
- ✅ `tests/test_summarize_integration.py::test_summarize_session_unsummarized` — 全未要約セッション GREEN
- ✅ `tests/test_summarize_integration.py::test_summarize_session_partial` — 部分要約セッション（1済・3未）GREEN

#### セッション状態管理UI拡張（2026-05-10）
- ✅ `GET /sessions/{session_id}/stats` — 会話数・要約済数・transcript未処理行有無を返すAPI
- ✅ `POST /sessions/{session_id}/ingest` — transcriptから未取込メッセージをevent storeへ取り込み＋indexer実行
- ✅ `db.py` に `get_session_stats` メソッド追加（conversation_count / summarized_count）
- ✅ `deps.py` に `get_snapshot_store` 依存追加
- ✅ `HomePage.tsx` — 5段階状態（未取込/取込中/取込済/要約中/要約済）ラベル表示（色分け）
- ✅ `HomePage.tsx` — 更新ボタン・取込ボタン・要約ボタン追加（各状態に応じて表示切替）
- ✅ `app.css` — 5段階状態バッジCSSクラス追加（オレンジ/黄色/緑）

#### 分析ステップ追加・7段階パイプライン（2026-05-12）
- ✅ **根本原因修正**: transcript取込は `MessageEvent` のみ生成 → `StopEvent` なし → `conversations` テーブルが空（会話0件）→ 取込済0/0 表示・要約ボタン非表示のバグ
- ✅ `src/replay/transcript_analyzer.py` — `system/turn_duration` エントリ（Stopフック相当）のタイムスタンプを境界に未インデックスイベントを会話単位へ分割。`turn_duration` 不在時は全イベントを1会話として扱うフォールバック付き
- ✅ `POST /sessions/{session_id}/analyze` — 取込済イベントを会話レコードに変換するエンドポイント追加（`claude_scan.py` に追記）
- ✅ `SessionStats` に `has_unanalyzed_events: bool` フィールド追加（`store.count_events > last_indexed + 1` で算出）
- ✅ `HomePage.tsx` — 7段階状態（未取込/取込中/取込済/分析中/分析済/要約中/要約済）に拡張
- ✅ `HomePage.tsx` — 分析ボタン追加（取込済・分析中のとき表示）
- ✅ `app.css` — `status-analyzing` / `status-analyzed` CSSクラス追加（黄色系）

#### ホームタブ バグ修正（2026-05-12）
- ✅ `src/replay/pipeline.py` — `asyncio.sleep` → `asyncio.Event` ベースの割り込み可能ウェイトに変更（`stop()` が即時反映）、`CancelledError` ハンドリング追加
- ✅ `src/api/main.py` — lifespan teardown に `pipeline_task.cancel()` + `asyncio.wait_for(..., timeout=5.0)` を追加（シャットダウン最大5秒で完了）
- ✅ `src/replay/summarizer.py` — `AsyncOpenAI` に `timeout=120.0` 追加（デフォルト600秒から削減）
- ✅ `web/src/HomePage.tsx` — `getSessionStatus`: `has_pending_transcript` と `conversation_count === 0` を分離（Stopフック未発火セッションが「取込中」のままになるバグ修正）
- ✅ `web/src/HomePage.tsx` — `showSummarize` に `conversation_count > 0` 条件追加（0会話セッションで要約ボタンが出るバグ修正）
- ✅ `web/src/App.tsx` + `HomePage.tsx` — `onSessionsRefresh` コールバック追加（取込後に `ingestedIds` が即時反映されるよう修正）
- 📝 **備考**: `Ctrl+C` 後ハングの主因は `uvicorn --reload` の watchfiles 未インストール。`poetry add watchfiles` で解消。pipeline 修正は2次的な堅牢化。

#### 静的型不一致チェッカー（2026-05-11）
- ✅ `src/analysis/ast_extractor.py` — AST解析（FunctionInfo / CallSiteInfo 抽出、リテラル型推論）
- ✅ `src/analysis/call_graph.py` — 呼び出しグラフ構築（callee名→FunctionInfo解決、CallEdge生成）
- ✅ `src/analysis/type_mismatch.py` — 型比較エンジン（プリミティブ型のみ対象、bool/int/float サブタイプ考慮、カスタム型・ジェネリック型は誤検知防止のためスキップ）
- ✅ `src/analysis/checker.py` — オーケストレーター（`check_directory(path) → CheckResult`、CLI `python -m src.analysis.checker`）
- ✅ `tests/test_type_checker.py` — 35テスト全GREEN（AST抽出・CGA・型比較・統合 + `test_no_type_mismatches_in_src` ガード）
- ✅ `.claude/rules/testing.md` — 静的型チェッカーの使用規約を追記（CLI実行・ガードテスト維持義務）
- ✅ `forUser/rules/testing.md` — 日本語対訳を同期更新
- ✅ `redesign_en.md` — "Static Type Mismatch Checker: AST + CGA + Type Analysis" セクション追記（モジュール設計・誤検知回避設計・CLI・MED非適用の旨を明記）

#### Vitest テストフック基盤（2026-05-13）
- ✅ `vitest` + `@vitest/coverage-v8` + `jsdom` + `@testing-library/{react,jest-dom,user-event}` インストール
- ✅ `web/vitest.config.ts` — jsdom環境・setupFiles 設定（pytest の conftest.py 相当）
- ✅ `web/src/test/setup.ts` — グローバルセットアップ（`@testing-library/jest-dom` import）
- ✅ `web/src/test/smoke.test.tsx` — スモークテスト（1 passed / GREEN確認済み）
- ✅ `web/package.json` — `test` / `test:run` / `test:coverage` スクリプト追加
- ✅ `web/tsconfig.json` — `"vitest/globals"` を `types` に追加
- ✅ `.claude/rules/ts-react-strict.md` — Testing セクション追加（Vitest hookテーブル・命名規則・CI契約）
- ✅ `forUser/rules/ts-react-strict.md` — 日本語対訳を同期更新
- ✅ `redesign_en.md` — Vitest フックシステム設計セクション追記（pytest対応表・パッケージ構成）

#### TypeScript / React デバッグ機構（2026-05-13）

静的解析（ts-morph / Node.js）:
- ✅ `web/scripts/analysis/ast-extractor.ts` — コンポーネント・フック呼び出しを ts-morph で抽出（ComponentInfo / HookCallInfo）
- ✅ `web/scripts/analysis/hook-checker.ts` — Rules of Hooks 違反（条件分岐内フック）・空依存配列 `[]` を検出
- ✅ `web/scripts/analysis/checker.ts` — CLI orchestrator（`pnpm analyze`、exit 1 で CI ブロック）
- ✅ `web/tsconfig.scripts.json` — Node.js スクリプト向け独立 tsconfig

動的解析（dev-only / React）:
- ✅ `web/src/debug/logger.ts` — 型付きイベントバッファ、2秒マイクロバッチで `/api/ingest` に POST（keepalive付き）
- ✅ `web/src/debug/useRuntimeLogger.ts` — mount / unmount / render数をログする hook

スキーマ拡張:
- ✅ `EventSource.FRONTEND` / `EventType.FRONTEND_DEBUG` を additive 追加（既存テスト全GREEN）
- ✅ `FrontendDebugEvent` モデル追加（component / lifecycle / data フィールド）

Rule・ドキュメント:
- ✅ `.claude/rules/ts-react-strict.md` — TypeScript/React 厳格ルール + analyze/RuntimeLogger 使用規約
- ✅ `forUser/rules/ts-react-strict.md` — 日本語対訳
- ✅ `web/package.json` に `"analyze"` スクリプト追加（ts-morph 28.0.0 / tsx 経由）

#### データフロー可視化ツールチェーン（2026-05-13）

Python 静的解析層:
- ✅ `src/analysis/db_schema_extractor.py` — DDL（regex）・Pydantic（AST）・SQLクエリ（string literal walk）抽出。ColumnInfo / SqlTableInfo / PydanticModelInfo / SqlQueryInfo / DbExtractionResult
- ✅ `src/analysis/route_extractor.py` — FastAPI `@router.METHOD()` デコレータを AST 解析して RouteInfo 抽出（path / method / handler_name / response_model / tags）
- ✅ `src/analysis/ir_builder.py` — 全解析結果を統合した中間表現（IR）生成。ノード ID 体系（`py:{module}:{qname}` / `api:{METHOD}:{path}` / `db:{table}` / `fe:*`）、関数フィルタ（ルートハンドラ起点 2ホップBFS + SQLクエリ関数）
- ✅ `src/api/routers/dataflow.py` — `GET /dataflow/ir` エンドポイント（asyncio.to_thread で同期IR生成を非同期化）
- ✅ `src/api/main.py` に `dataflow` ルーター追加

TypeScript 静的解析層:
- ✅ `web/scripts/analysis/fetch-extractor.ts` — ts-morph で `fetch()` コールサイト抽出（テンプレートリテラル `${BASE}/path/${id}` → `{*}` 正規化対応）
- ✅ `web/scripts/analysis/ir-exporter.ts` — フロントエンドIRを `runtime/frontend_analysis.json` に書き出す（`pnpm analyze:ir`）
- ✅ `web/package.json` に `"analyze:ir"` スクリプト追加

React フロントエンド:
- ✅ `web/src/components/dataflow/types.ts` — IRNode / IREdge / DataFlowIR 型定義
- ✅ `web/src/components/dataflow/FlowGraph.tsx` — ReactFlow v12 + dagre LR レイアウト、ノード種別ごとに色分け（component/hook/fetch_call/route/function/pydantic/table）
- ✅ `web/src/pages/DataFlowPage.tsx` — `GET /dataflow/ir` フェッチ、レイヤーフィルターチェックボックス付き
- ✅ `web/src/App.tsx` — 「データフロー」ナビボタン追加（4ページ目）
- ✅ `web/src/app.css` — dataflow-page / dataflow-controls / dataflow-graph スタイル追加

テスト・品質:
- ✅ `tests/test_db_schema_extractor.py` — 22テスト（DDL列パース・Pydantic抽出・SQLクエリ・組合せ）
- ✅ `tests/test_route_extractor.py` — 10テスト（全HTTPメソッド・response_model・タグ・同期/非同期）
- ✅ 32テスト全GREEN、`tsc --noEmit` エラーゼロ
- ✅ `web/package.json` `pnpm.onlyBuiltDependencies` に `esbuild` 追加 + pnpm-lock.yaml 再生成（esbuild ビルドスクリプト承認）

#### 動的型不一致検出（typeguard + AST + CGA）
- ⬜ `typeguard` を dev依存に追加（`poetry add --group dev typeguard`）
- ⬜ `src/analysis/call_graph.py` に `build_reverse_call_graph()` 追加（callee→callers逆引き）
- ⬜ `src/analysis/dynamic_checker.py` — TypeCheckErrorパース + 既存AST/CGA統合 + レポート生成（JSON/Markdown）
- ⬜ `tests/test_dynamic_checker.py` — typeguard有効化時のTypeCheckError検出・AST復元・CGA逆引きテスト
- ⬜ Stop Hookには追加しない（オーバーヘッド大）—on-demand実行のみ: `pytest tests/ --typeguard-packages=src`

#### 要約プロバイダー設定画面（WebGUI）
- ⬜ `GET /settings/summarizer` / `PUT /settings/summarizer` — プロバイダー設定API（backend種別・base_url・api_key・model を runtime/settings.json に永続化）
- ⬜ `SettingsPage.tsx` — 要約バックエンド設定フォーム（OpenAI互換 / Claude API 切り替え、base_url・model入力、テスト接続ボタン）
- ⬜ `GET /conversations/{id}/summarize` 結果をWebGUIの会話リストに反映（要約ボタン追加）

---

### STEP 4 — UMAP・TemporalVectorKB下地（v1.2設計 §3）

- ✅ topicベクトル化（sentence-transformers `all-MiniLM-L6-v2`、DBキャッシュ付き）
- ✅ UMAPバッチ生成（`src/replay/umap_runner.py`、n_neighbors guard付き）
- ✅ Plotlyによるscatter出力（session別 / 月別の色分け、react-plotly.js でGUI表示）
- ✅ 時間窓フィルタ（since / until クエリパラメータ、`GET /umap`）
- ✅ `GET /umap` FastAPIエンドポイント（session_id / since / until / color_by 対応）
- ✅ トピックマップページ（`UmapPage.tsx`）— GUI第3ページとして追加
- ⬜ Multi-source adapter（webchat / Discord Bot / Gemini CLI）
- ⬜ Cross-session topic graph
- ⬜ TemporalVectorKB統合

---

## 保留・検討中

- ✅ パッケージマネージャ選定（poetry を採用・運用中）
- ⏸ xterm.js fallback terminal（GUIオプション）
- ⏸ Topic重要度按分集計（移動平均の後継、TemporalVectorKB統合時に検討）
- ⏸ UMAP リアルタイム更新（v1.2時点はバッチのみ）
- ⏸ セマンティッククラスタリング（STEP 4以降）

---

_最終更新: 2026-05-13 — データフロー可視化ツールチェーン追加（DB/Route/IR Python静的解析、fetch-extractor/ir-exporter TypeScript解析、ReactFlow+dagre グラフUI、GET /dataflow/ir API）、32テスト全GREEN、pnpm esbuild ビルドスクリプト問題修正_
