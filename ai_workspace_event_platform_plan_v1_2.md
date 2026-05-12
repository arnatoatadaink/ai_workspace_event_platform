# AI Workspace Event Platform Plan v1.2

## 現在の名称候補

現時点の構成思想として最も近い名称：

- AI Workspace Event Platform
- AI Event Sourcing Workspace
- Unified AI Interaction Journal
- Agent Workspace Runtime
- AI Interaction Operating Layer

現段階では以下を暫定名称として採用：

# AI Workspace Event Platform

理由：
- CLI限定ではない
- WebGUIも統合対象
- journal/event sourcing中心
- adapter/plugin構造を持つ
- 複数AI interaction sourceを統合可能

---

# 目的

Claude CLIを中心としたAI interactionを：

- 構造化
- journal化
- topic抽出
- replay
- GUI可視化
- 横断検索

可能な状態へ統合する。

また、将来的に：

- Web Chat
- Discord Bot
- Gemini CLI
- OpenAI系
- Aider

などをadapter pluginによって統合可能な構造とする。

---

# コア思想

## ログではなくイベントを保存する

従来：

```text
CLI Log
```

本設計：

```text
AI Interaction Event Stream
```

へ昇格する。

---

# 全体アーキテクチャ

```text
Source
  ↓
Adapter Plugin
  ↓
Normalizer
  ↓
Internal Event Schema
  ↓
Append-only Event Store
  ↓
Replay Engine
  ↓
Summary / Topic Pipeline
  ↓
FastAPI
  ↓
React WebGUI
```

---

# Source Layer

## 初期対応

- Claude CLI

## 将来的対応

- Web Chat UI
- Discord Bot
- Gemini CLI
- OpenAI CLI
- Aider
- Codex

---

# Adapter Plugin Layer

## 目的

外部ソース依存を隔離する。

GUI・Replay・Topic Pipelineは
source固有仕様を知らない状態にする。

---

## 構造

```text
adapters/
  claude/
  webchat/
  aider/
  gemini/
```

---

## Claude Adapter責務

- Hook解析
- transcript_path取得
- Hook schema同期
- raw event取得
- internal event変換

---

# Hook Schema System

## 方針

Claude Hook仕様をJSON Schema化する。

---

## 入力対象

```text
.claude/
  settings.json
  hooks.json
  commands/
```

および実Hook payload。

---

## 構造

```text
schemas/
  claude/
    stop_hook_v1.schema.json
    pre_tool_use.schema.json
```

---

## 目的

- Claude更新追従
- Hook変更吸収
- 型安全化
- adapter生成支援
- GUI安定化

---

# Hook Protocol Layer

## 方針

Hook出力解析ではなく：

```text
構造化Hook Event
```

を使用する。

---

## Hook Event例

```json
{
  "schema": "stop_hook_v2",
  "event": "approval_required",
  "session_id": "...",
  "payload": {}
}
```

---

# Internal Event Schema

## 方針

Claude依存schemaを直接GUIへ流さない。

必ずinternal eventへ変換する。

---

## 例

```json
{
  "type": "approval_required",
  "source": "claude_cli",
  "session_id": "...",
  "timestamp": "...",
  "payload": {}
}
```

---

## 利点

- GUI安定化
- source抽象化
- replay互換
- plugin統合

---

# Event Store

## 方針

append-only JSONL event sourcing。

---

## 構造

```text
runtime/
  sessions/
    session_x/
      events.jsonl
      raw.log
      summaries.json
      topics.json
      state.json
```

---

## 保存対象

- assistant message
- user message
- tool call
- approval request
- stop hook
- summary update
- topic extraction
- state update

---

# Replay Engine

## 方針

event streamから状態再構築可能にする。

---

## 利点

- GUI復元
- topic再生成
- summary更新
- embedding再計算
- analytics

---

# Transcript Integration

## 方針

transcript全文をeventへ埋め込まない。

---

## 方式

```json
{
  "transcript_ref": {
    "message_index": 152
  }
}
```

---

## 利点

- 重複削減
- replay高速化
- storage効率化

---

# Summary / Topic Pipeline

## 現状想定

Gemma系モデルによる：

- turn summary
- long summary
- topic extraction

---

## 推奨構造

```json
{
  "summary_short": "...",
  "summary_long": "...",
  "topics": []
}
```

---

# FastAPI Layer

## 役割

- Event API
- Session API
- Replay API
- WebSocket stream
- Search API

---

## 想定API

```text
GET /sessions
GET /events
GET /topics
GET /search
WS /stream
```

---

# React WebGUI

## 方針

ターミナルではなく：

```text
構造化イベントUI
```

を主役にする。

---

## UI構造

```text
┌──────────────┬───────────────┐
│ セッション一覧 │ メッセージ詳細 │
│ 要約表示       │ transcript     │
├──────────────┼───────────────┤
│ topic一覧      │ 関連イベント    │
└──────────────┴───────────────┘
```

---

## 補助UI

xterm.jsをfallback terminalとして併設可能。

---

# Stop Hook設計

## 方針

Hook仕様変更を前提とする。

そのため：

```text
schema registry
```

による同期を行う。

---

## 重要

stdout解析依存を最小化する。

---

# Multi Source Journal

## 方針

すべてのAI interaction sourceを
同一journalへ統合可能にする。

---

## 例

- Claude CLI
- Web Chat
- Discord Bot
- Gemini CLI

を同一topic graphへ統合。

---

# Topic Graph

## 将来構想

- cross-session topic link
- semantic cluster
- UMAP visualization
- memory graph

---

# 実装優先順位

## STEP 1

- Claude adapter
- Hook schema extractor
- Internal event schema v1
- Event store(JSONL)

---

## STEP 2

- Replay engine
- Summary pipeline
- Topic extraction
- FastAPI API

---

## STEP 3

- React GUI
- Session explorer
- Topic navigation
- Search UI

---

## STEP 4

- Multi source adapter
- Cross-session topic graph
- UMAP visualization
- Analytics

---

# v1.1 更新内容

## 設計方針の明確化

### 不変層

以下をコア固定層として扱う：

```text
Internal Event Schema
Event Store(JSONL)
```

これらはシステム全体の事実記録層として扱い、
Replay・Topic・Summary・GUI変更の影響を受けない。

---

### 可変層

以下はplugin化・交換可能設計とする：

```text
Replay Engine
Topic Graph Builder
Summary Pipeline
Semantic Projection
GUI Projection
```

---

# Adapter Plugin Loading v1.1

## 方針

現段階では：

```text
FastAPI startup時ロード
```

を採用。

---

## Plugin Isolation

現段階では：

```text
low isolation
```

を採用。

pluginは本体Python process内で実行する。

---

## 理由

- 開発容易性
- 型共有
- event schema統一
- 実装速度優先

---

# Event Store Rotation v1.1

## 方針

```text
session + chunk
```

構成を採用。

---

## 構造

```text
runtime/
  sessions/
    session_x/
      events_0001.jsonl
      events_0002.jsonl
```

---

## 理由

- 長時間session対応
- append効率
- replay高速化
- corruption局所化

---

## Conversation分離

conversation切り分けは：

```text
Replay / Analysis Layer
```

で後処理として行う。

Event Storeでは扱わない。

---

# Transcript Parser v1.1

## 初期方針

最初は：

```text
message only
```

構成で開始。

---

## 拡張方針

追加情報抽出は：

```text
Extractor Plugin
```

で後から追加可能にする。

---

## 想定将来対象

- tool call
- metadata
- timestamps
- hook relation
- attachments
- reasoning-like structures

---

# Replay Architecture v1.1

## 方針

Replay Engineはplugin化する。

---

## Replayの定義

Replayとは：

```text
event streamから意味状態を再構築する層
```

である。

GUI専用機能ではない。

---

## Delta Replay

```text
snapshot
+
差分event replay
```

方式を採用。

---

## Full Replay

毎回event先頭から全replayする方式は採用しない。

---

## Replay Plugin例

- session replay
- timeline replay
- topic replay
- semantic replay
- agent replay

---

# Topic Graph v1.1

## 方針

Topic Graphは：

```text
semantic projection layer
```

として扱う。

---

## 位置付け

```text
Replay
  ↓
Topic Extraction
  ↓
Topic Graph Builder
```

---

## Temporal KBとの関係

Temporal Vector KBとの責務共有領域として扱う。

topic graphはevent store本体ではなく：

```text
semantic replay結果
```

として生成する。

---

# Git連携前提 v1.1

## 方針

簡易版実装では：

```text
JSONL + session directory
```

構造をGit管理可能な形で維持する。

---

## 理由

- replay実験
- schema変更追跡
- event差分比較
- summary更新追跡
- topic graph比較

を容易にするため。

---

# v1.1時点の推奨簡易実装

## Core

- FastAPI
- React
- JSONL Event Store
- Claude Adapter
- Hook Schema Extractor
- Internal Event Schema v1

---

## Optional

- xterm.js fallback terminal
- Topic Extraction
- Summary Pipeline
- Temporal KB integration

---

# v1.1時点の設計上の特徴

本設計は：

```text
CLI GUI
```

ではなく、

```text
AI Event Sourcing Workspace
```

に近い。

特に：

- normalized event schema
- replay architecture
- plugin adapter
- journal system
- topic graph

を中心とした構造になっている。

---

# v1.2 更新内容

## Replay Engine以降の設計詳細化

v1.1ではReplay Engineをplugin化・Delta Replay採用として位置付けた。
v1.2では「初期化処理」「GUI参照処理」「UMAPマップ生成」の3段階に分けて設計を具体化する。

---

# Replay Snapshot Metadata v1.2

## 方針

snapshotは単なる状態ダンプではなく、
検索・可視化・差分追跡に使えるメタデータを持たせる。

---

## メタデータ構成

```json
{
  "snapshot_id": "...",
  "created_at": "...",
  "event_range": {
    "chunk_first": "events_0001.jsonl",
    "chunk_last": "events_0004.jsonl",
    "event_index_start": 0,
    "event_index_end": 38420
  },
  "context_length": {
    "event_count": 38420,
    "estimated_tokens": 120000
  },
  "chunk_count": 4,
  "topic_summary": {
    "topics": ["...", "..."],
    "umap_projection": [[0.12, 0.45], [0.88, 0.31]]
  }
}
```

---

## snapshot vs delta の日付フィールド

| フィールド | snapshot | delta |
|-----------|----------|-------|
| `created_at` | ✅ | ✅ |
| `updated_at` | ❌（不変） | ✅ |

snapshotは不変なので `created_at` のみ持つ。
deltaは適用のたびに `updated_at` を更新する。

---

# 初期化処理 v1.2

## 位置付け

新しいsession chunkをEvent Storeから読み込んだ際に行う重い処理。
Event Store本体には触れず、DB上の索引とsummaryを構築する。

---

## 1-1. Session Chunk → 会話単位インデックス

### 方針

Event Store上のchunk（JSONL）はrotation都合で分割されている。
これをengine上で**会話単位**に再分割し、DBへ索引として保存する。

---

### 索引構造

```text
DB: conversations テーブル
  - conversation_id
  - session_id
  - chunk_file_first        ← 会話が始まるchunkファイル名
  - chunk_file_last         ← 会話が終わるchunkファイル名
  - event_index_start
  - event_index_end
  - created_at
  - message_count
```

---

### 参照フロー

```text
最新の会話を取得:
  SELECT * FROM conversations
  ORDER BY created_at DESC LIMIT 1

遡って取得:
  SELECT * FROM conversations
  WHERE session_id = ?
  ORDER BY created_at DESC
  OFFSET n LIMIT 1
```

---

## 1-2. 会話単位の要約生成

### 方針

会話インデックス（1-1）を参照しながら、
3段階の粒度の情報を生成してDBへ保存する。

---

### 3段階粒度

```text
粒度1: conversation
  event_index_start〜endの生イベント列（Event Storeを参照）

粒度2: summary
  会話全体の短い要約テキスト（LLMで生成）
  summary_short / summary_long

粒度3: topic
  会話から抽出されたtopic列
  ["Python", "FastAPI", "Event Sourcing", ...]
```

---

### DB構造

```text
DB: conversation_summaries テーブル
  - conversation_id         ← conversations テーブルのFK
  - summary_short
  - summary_long
  - topics (JSON array)
  - generated_at
  - model_used
```

---

## 1-n. Snapshot・Delta との兼ね合い

### chunk末尾からの逆引き取得

新しいchunkが追加された際、
chunk末尾から遡って未処理の会話を特定する処理を追加する。

```text
処理フロー:
  1. 最新chunkファイルを取得
  2. DBの最後に処理済みの event_index_end を取得
  3. 差分（未処理イベント列）を抽出
  4. 会話境界を検出して新規会話レコードを追加
  5. 新規会話分のsummary・topicを生成
```

---

### snapshot更新タイミング

```text
- 新規会話インデックス追加後にsnapshotを更新
- snapshotはchunk単位で切る（全session再計算は行わない）
- 古いsnapshotはアーカイブとして保持（event_range付き）
```

---

# GUI参照処理 v1.2

## 位置付け

FastAPI経由でGUIに提供するsession参照API群。
Replay Engineの索引（DB）を読むだけで、Event Storeを直接スキャンしない。

---

## 2-1. セッション最新会話からのロード

### 方針

GUIは常に「最新の会話」から表示を開始する。
ユーザーが過去に遡る操作をすると、会話インデックスを逆順に辿る。

---

### API設計

```text
GET /sessions/{session_id}/conversations
  ?order=desc
  &limit=10
  &before_conversation_id=<id>   ← ページング用カーソル

Response:
  [
    { "conversation_id": "...", "summary_short": "...", "topics": [...], ... },
    ...
  ]
```

---

### GUI操作フロー

```text
1. セッション選択 → 最新会話を取得
2. 会話詳細クリック → event_index_start〜endからイベント取得
3. 「もっと前を見る」 → before_conversation_idでページング
4. 会話内スクロール → transcript_refでtranscript参照
```

---

## 2-2. Topic追従（TemporalVectorKB関連）

### 方針

最新の会話の要約を逐次追従し、
現在のsession内で「継続している話題」を可視化する。

---

### 移動平均によるtopic集計

初期実装として機械的な移動平均を採用する。

```text
直近 N 会話のtopicリストを収集
  ↓
topic出現頻度を集計
  ↓
時系列順に移動平均を計算（window size = W）
  ↓
上位K topicを「現在アクティブなtopic」として返す
```

```json
{
  "active_topics": [
    { "topic": "FastAPI", "weight": 0.82, "trend": "stable" },
    { "topic": "Event Sourcing", "weight": 0.67, "trend": "rising" },
    { "topic": "UMAP", "weight": 0.41, "trend": "new" }
  ],
  "window": { "conversations": 10, "from": "...", "to": "..." }
}
```

---

### 将来拡張: 重要度按分による集計

移動平均の後続候補として：

```text
- 会話の長さ・density による重み付け
- LLMによるtopic重要度スコアリング
- ユーザーの発話量によるbias補正
```

現段階では移動平均のみ実装し、
按分方式はTemporalVectorKB統合時に検討する。

---

# UMAPマップ生成 v1.2（TemporalVectorKB下地）

## 位置付け

全session・全sourceのtopicをひとつの2D空間に投影する。
TemporalVectorKBの視覚化基盤として機能する。

---

## 入力

```text
Replay Engineが読み込んでいる範囲のtopicベクトルを使用。
全session・全sourceを対象とする（クロスドメイン集計）。
```

---

## 出力: Plotlyによる可視化

他プロジェクトでの実績に従いPlotlyで出力する。

```text
scatter plot:
  x, y  : UMAP投影座標
  color : source または session（切り替え可能）
  size  : topic出現頻度
  label : topic名
```

---

## 色分けの軸

| 軸 | 目的 |
|----|------|
| source別 | どのAIツール（Claude/Gemini等）でどのtopicを扱ったか |
| session別 | どのsessionでどのtopicが近接しているか |
| 時間窓別 | いつどのtopicを扱っていたか |

---

## 時間窓フィルタ

```text
時間単位のwindowを指定してUMAPを再描画できるようにする。

例:
  「2026-04の会話のtopicマップ」
  「直近30日のtopicマップ」
  「このsessionのtopicマップ」

→ Replay Engineの event_range を絞り込んで再計算
```

---

## topic島の構造

```text
近接するtopicが自然にクラスタを形成することで
「話題の島」が生まれる。

期待される島の例:
  - Python / FastAPI / Pydantic 島
  - Event Sourcing / JSONL / Replay 島
  - LLM / Embedding / UMAP 島
```

---

## v1.2時点の実装範囲

UMAPマップはReplay Engineが読み込んでいる範囲を対象とする。
リアルタイム更新は行わず、バッチ生成とする（GUIからのリクエストに応じて再生成）。

---

# v1.2実装優先順位（追加分）

## STEP 2（拡張）

- Replay初期化: session chunk → 会話インデックスDB（1-1）
- Replay初期化: 会話単位summary・topic生成（1-2）
- snapshot metadata 構造定義
- chunk末尾逆引き差分処理（1-n）

## STEP 3（拡張）

- GUI: 最新会話からのロードAPI（2-1）
- GUI: 会話一覧ページング
- GUI: Topic追従（移動平均）（2-2）

## STEP 4（拡張）

- UMAPマップ生成バッチ（Plotly出力）
- source・session・時間窓による色分け
- TemporalVectorKB統合の下地整備

