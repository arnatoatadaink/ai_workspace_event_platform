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
- ✅ Stop フック `transcript_path` 疎通修正 — 調査結果: MessageEvent はパイプライン（`/ingest`）経由で既に存在。Stop フック payload に `transcript_path` が含まれない問題は `adapter.py` のフォールバック導出（CWD→スラグ→`~/.claude/projects/<slug>/<session_id>.jsonl`）で解消。スラグヘルパーを `src/adapters/claude/paths.py` に共有モジュール化。`ChatPane.tsx` の古い TODO メッセージを「取込→分析を実行」ヒントに更新。

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

#### データフロー可視化 — フローハイライト（2026-05-13）
- ✅ `web/src/components/dataflow/FlowGraph.tsx` — ノードクリックでフローハイライト機能追加
  - 上流 BFS（逆方向エッジ辿り）+ 下流 BFS（順方向エッジ辿り）で経路ノード/エッジを算出
  - ノード状態: `selected`（白枠+光彩）/ `path`（白ボーダー）/ `dimmed`（opacity 0.18）/ `normal`
  - エッジ状態: 経路上は白・太・アニメーション、経路外はほぼ透明
  - 同ノード再クリック / 背景クリックで選択解除
  - dagre レイアウト計算（重い）は IR 変更時のみ、ハイライト計算はクリック時のみ（別 useMemo）
- ✅ `web/src/pages/DataFlowPage.tsx` — 操作ヒント文言追加（「ノードをクリック → フローをハイライト」）
- ✅ `web/src/app.css` — `.dataflow-hint` スタイル追加

#### データフロー可視化ツールチェーン — APIからTSXまで（2026-05-13）

TypeScript→API接続層（2026-05-13追加）:
- ✅ `web/scripts/analysis/fetch-extractor.ts` — `enclosingFunctionName` バグ修正（`const res = await fetch(...)` の `VariableDeclaration` を関数ではなく変数として正しく扱うよう修正）
- ✅ `web/scripts/analysis/ir-exporter.ts` — `IRNode.kind` に `"function"` 追加、`IREdge.kind` に `"calls"` 追加
- ✅ `web/scripts/analysis/ir-exporter.ts` — 呼び出し元→fetch_callノード間の `calls` エッジ生成（API ユーティリティ関数ノード `fe:function:X` を自動生成）
- ✅ 完全チェーン: `fe:function:fetchSessions` → `fe:fetch:GET:/sessions` → `api:GET:/sessions` → `py:function` → `db:table`

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
- ✅ `typeguard` を dev依存に追加（`poetry add --group dev typeguard`）
- ✅ `src/analysis/call_graph.py` に `build_reverse_call_graph()` 追加（callee→callers逆引き）
- ✅ `src/analysis/dynamic_capture.py` — pytest hookwrapper（`pytest_runtest_makereport`）で TypeCheckError を `runtime/dynamic_check_events.jsonl` に JSONL 書き出し。`parse_typeguard_message()` / `extract_user_frames()` ヘルパー付き
- ✅ `src/analysis/dynamic_checker.py` — JSONL 読み込み + AST/CGA 結合 + JSON/Markdown レポート生成（`run_check()` CLI エントリーポイント）
- ✅ `tests/conftest.py` — `pytest_plugins = ["src.analysis.dynamic_capture"]` でプラグイン登録
- ✅ `tests/test_dynamic_checker.py` — 22テスト全GREEN（メッセージパース・フレーム抽出・逆CGA・イベント読み込み・エンリッチ・レポート生成・統合）
- ✅ Stop Hookには追加しない（オーバーヘッド大）— on-demand実行のみ: `pytest tests/ --typeguard-packages=src` → `python -m src.analysis.dynamic_checker`

#### 要約プロバイダー設定画面（WebGUI）
- ✅ `GET /settings/summarizer` / `PUT /settings/summarizer` / `POST /settings/summarizer/test` — プロバイダー設定API（backend種別・base_url・api_key・model を runtime/settings.json に永続化、APIキーはGETでマスク）
- ✅ `src/api/settings_store.py` — 設定読み書き・APIキーマスク・バックエンド構築ヘルパー（ファイルモード 0600）
- ✅ `SummaryTopicPipeline.update_summarizer()` — ランタイム差し替えセッター追加
- ✅ `src/api/main.py` — lifespan で runtime/settings.json から設定を読み込みバックエンドを初期化
- ✅ `SettingsPage.tsx` — 要約バックエンド設定フォーム（OpenAI互換 / Claude API 切り替え、base_url・model入力、テスト接続ボタン・保存フィードバック）
- ✅ `ConversationPane.tsx` — 未要約会話に「要約する」ボタン追加（クリックで即時反映）

---

### STEP 4 — UMAP・TemporalVectorKB下地（v1.2設計 §3）

- ✅ topicベクトル化（sentence-transformers `all-MiniLM-L6-v2`、DBキャッシュ付き）
- ✅ UMAPバッチ生成（`src/replay/umap_runner.py`、n_neighbors guard付き）
- ✅ Plotlyによるscatter出力（session別 / 月別の色分け、react-plotly.js でGUI表示）
- ✅ 時間窓フィルタ（since / until クエリパラメータ、`GET /umap`）
- ✅ `GET /umap` FastAPIエンドポイント（session_id / since / until / color_by 対応）
- ✅ トピックマップページ（`UmapPage.tsx`）— GUI第3ページとして追加
- ⏸ Multi-source adapter（webchat / Discord Bot / Gemini CLI）
  > ⚠️ **規約懸念**: 各プラットフォームの利用規約・API Terms of Service を実装前に確認すること。
  > - **Discord Bot**: Discord ToS § 2.5 / Developer Policy — ユーザーメッセージの第三者ストレージは原則禁止。Bot 経由の自動収集はサーバー管理者の同意とユーザーへの開示が必要。
  > - **Webchat（LINE/Slack 等）**: 各社の Developer Agreement により取得データの目的外利用・再配布が制限される場合がある。Slack の場合は Customer Data の定義とデータ処理補足書（DPA）の確認が必須。
  > - **Gemini CLI**: Google API Terms of Service / Generative AI Additional Terms — Google サービスを経由したデータのローカル永続化可否を確認すること。
  > - **共通**: 個人情報保護法（日本）・GDPR（EU）の観点から、個人を特定しうるチャットログの保存・処理にはデータ主体の同意フローと削除対応が必要になる可能性がある。
- ✅ Cross-session topic graph
  - `src/replay/topic_graph.py` — `_aggregate_rows` / `_scale_to_canvas` / `_build_edges` 純粋関数 + `build_topic_graph()` async オーケストレーター
  - `src/api/routers/topic_graph.py` — `GET /topic-graph`（min_topic_count / min_shared_sessions パラメータ）
  - `web/src/pages/TopicGraphPage.tsx` — ReactFlow + UMAP座標配置、セッション数カラー、サイズ＝出現頻度、詳細パネル
  - `tests/test_topic_graph.py` — 17テスト全GREEN（純粋関数単体テスト）
- ✅ TemporalVectorKB統合（下地完了として閉じる）
  - UMAP + 埋め込みキャッシュ（DB）が設計 §3 の「下地整備」に相当
  - topic vector k-NN クエリ・時間軸スライスは将来ステップへ持ち越し

---

## 保留・検討中

- ✅ パッケージマネージャ選定（poetry を採用・運用中）
- ⏸ xterm.js fallback terminal（GUIオプション）
- ⏸ Topic重要度按分集計（移動平均の後継、TemporalVectorKB統合時に検討）
- ⏸ UMAP リアルタイム更新（v1.2時点はバッチのみ）
- ⏸ セマンティッククラスタリング（STEP 4以降）

---

#### 表示状態バグ修正（2026-05-13）
- ✅ `web/src/HomePage.tsx` — `getSessionStatus`: `has_unanalyzed_events` チェックを要約進捗チェックより後に移動。旧ロジックでは `summarized_count>0` でも `has_unanalyzed_events=true` なら「分析中」に落ちていた（例：`conv=2, sum=1, unanalyzed=true` → 「分析中」で要約ボタン非表示）。修正後は要約進捗を優先し `summarized_count > 0` なら「要約中」、全要約済みでかつ未分析イベントがある場合のみ「分析中」に。
- ✅ `web/src/HomePage.tsx` — `showAnalyze` / `showSummarize` をステータス文字列ではなく `stats` 直接参照に変更。`showAnalyze = stats.has_unanalyzed_events`、`showSummarize = conv > 0 && summarized < conv`。これにより「分析中」状態でも未要約会話があれば要約ボタンが表示され、矛盾を解消。

#### パイプライン別系統化・取り込み補完修正（2026-05-13）
- ✅ **根本原因**: stop hook と同一カーソル (`{session_id}.cursor`) をパイプラインが使用 → hook がカーソルを進めた後はパイプラインが 0件取り込み → `run_incremental_update` は StopEvent なしで会話レコード生成不可 → 「取り込み済0/0」バグ
- ✅ `src/adapters/claude/transcript.py` — `parse_transcript_messages` に `apply_migration_guard: bool = True` 追加。パイプライン側は `False` で呼び出し（UUID 重複排除で代替）
- ✅ `src/api/routers/claude_scan.py` — パイプライン専用カーソル `{session_id}.pipeline.cursor` を導入し hook カーソルと完全分離
- ✅ `src/api/routers/claude_scan.py` — `_collect_existing_event_ids` ヘルパー追加（生JSON解析で event_id セットを構築、Pydantic パース不要）。ingest 時に UUID 重複排除してストア重複書き込みを防止
- ✅ `src/api/routers/claude_scan.py` — `run_incremental_update`（StopEvent 依存 indexer）を ingest エンドポイントから削除。会話レコード生成は analyze エンドポイントで分担
- ✅ `src/replay/db.py` — `get_conversation_index_ranges()` 追加。セッションの全会話の (event_index_start, event_index_end) ペアを返す
- ✅ `src/replay/transcript_analyzer.py` — analyze を「未カバーイベント」ベースに再設計:
  - `_collect_events_from(store, session_id, start_from_idx=0)` — ストア全イベント収集
  - `_find_uncovered_events(all_events, existing_ranges)` — DB カバー済み範囲外イベントを抽出
  - `analyze_transcript_session` — 未カバーイベントを `turn_duration` 境界で分割して会話レコード追加（既存レコード削除なし・共存）
  - trailing events 対応: 最終 turn_duration 後の進行中イベントも会話として保存
- ✅ `src/api/routers/sessions.py` — `has_pending_transcript`: stop hook カーソル → pipeline カーソルベースに変更
- ✅ `src/api/routers/sessions.py` — `has_unanalyzed_events`: `event_count > last_indexed + 1` → `event_count > sum(end-start+1 for covered ranges)` に変更。マージ conv(4+5) での false positive 解消・非連続ギャップも検出可能

#### ホームタブ バグ修正（2026-05-13 追加分）
- ✅ `web/src/HomePage.tsx` — `getSessionStatus`: `summarized_count === conversation_count` のとき `has_unanalyzed_events` に関わらず「要約済」を返すよう修正。旧ロジックでは trailing unanalyzed events があると全会話要約済みでも「分析中」に落ちていた。

#### 既知バグ（低優先度）
- ⬜ **会話数 +1 重複表示**: ホームタブの会話カウント（`summarized_count/conversation_count`）が実際より1多く表示されることがある。`analyze_transcript_session` が trailing events を会話として保存する際、既存レコードと境界が重なって二重計上されている可能性がある。影響は表示のみ（データ破壊なし）。優先度: 低。

#### CrossProject処理（2026-05-16）
- ✅ `conversations` テーブルに `project_id TEXT` カラム追加（ALTER TABLE マイグレーション + 新規テーブル定義）
- ✅ `GET /claude/scan-projects` 新設（`~/.claude/projects/*` を列挙）
- ✅ `GET /claude/scan-sessions` に `project_id` / `all_projects` クエリパラメータ追加（全プロジェクト横断スキャン）
- ✅ `POST /sessions/{id}/analyze` — transcript パスから `project_id` を自動導出（全プロジェクト検索フォールバック付き）
- ✅ `GET /sessions` レスポンスに `project_id` を追加（DB問い合わせ）
- ✅ `_has_pending_transcript` を全プロジェクト横断検索に変更
- ✅ `web/src/api.ts` — `SessionInfo` / `ScannedSession` に `project_id` 追加、`ProjectInfo` 型・`fetchScannedProjects()` 追加
- ✅ `HomePage.tsx` — セッション一覧をプロジェクト別グループ表示（スラグ → パス逆変換）
- ✅ `scripts/install-hooks.sh` — Hook設定インストーラースクリプト（Stop / PreToolUse / PostToolUse、jq/Python両対応、べき等）

#### CrossProject 保留・バックログ
- ⬜ **プラットフォーム丸ごとインストール** — API + DB + GUI を別環境に一括展開（Docker化 / setup.sh）。スコープが大きいため将来ステップ。

#### 要約インターバル・クールダウン（2026-05-16）
- ✅ `src/api/summarization_throttle.py` — `SummarizationThrottle` 新設。`asyncio.Lock` で全要約呼び出しをグローバル直列化。クールダウン式: `wait = fixed_interval_seconds + elapsed × proportional_factor`。設定はディスクから毎回再読み込みのため再起動不要。
- ✅ `src/api/settings_store.py` — `SummarizationIntervalSettings` モデル追加（`fixed_interval_seconds` / `proportional_factor`、両方 0 で無効）。`load_interval_settings` / `save_interval_settings` 追加。内部ヘルパー `_load_raw` / `_save_raw` に整理（summarizer 設定と同一 JSON ファイルへの読み書きが競合しないよう）。
- ✅ `GET /settings/summarization-interval` / `PUT /settings/summarization-interval` — インターバル設定 API
- ✅ `src/api/main.py` + `deps.py` — lifespan で `SummarizationThrottle` を `app.state.throttle` に登録、`get_throttle` dep 追加
- ✅ `POST /conversations/{id}/summarize` + `POST /sessions/{id}/summarize` — 両エンドポイントで `throttle.run()` を適用（グローバル直列化）
- ✅ `SettingsPage.tsx` — 「要約インターバル（クールダウン）」セクション追加（固定インターバル秒・比例係数フォーム、保存フィードバック付き）

_最終更新: 2026-05-16 — 要約インターバル・クールダウン追加: グローバル直列化スロットル + 固定/比例インターバル設定画面_
