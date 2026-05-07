# AI Workspace Event Platform Plan

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

# 現時点の設計上の特徴

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

