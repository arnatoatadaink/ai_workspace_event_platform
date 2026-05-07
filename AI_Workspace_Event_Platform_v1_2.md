# AI Workspace Event Platform v1.2 Notes

## Replay中心設計と既存システムとの責務整理

---

# 基本思想

現在の設計は：

```text
CLI GUI
```

ではなく、

```text
AI Interaction Runtime Ecosystem
```

に近い。

特に重要なのは：

```text
Event Store を不変層に固定し、
Replay以降を意味論層として分離
```

した点。

---

# システム責務整理

## 1. Event Workspace System（今回のシステム）

### 本質
```text
AI interaction event runtime
```

### 責務
- Event収集
- Internal Event Schema
- Session/chunk管理
- Replay
- Journal
- Session GUI
- Topic追従
- Timeline
- Source統合

### 位置付け
```text
AI interaction OS layer
```

---

## 2. TVKB（Temporal Vector KB）

### 本質
```text
semantic memory layer
```

### 責務
- temporal retrieval
- semantic continuity
- context reconstruction
- memory retrieval
- vector indexing
- temporal relation

### 位置付け
```text
Replay結果を長期意味記憶へ変換する層
```

---

## 3. MED

### 本質
```text
semantic optimization / learning system
```

### 責務
- embedding optimization
- FAISS evolution
- NEAT experimentation
- semantic topology
- UMAP domain map
- external memory training

### 位置付け
```text
意味空間そのものを研究・最適化する層
```

---

## 4. AIHub

### 本質
```text
integration/runtime transport layer
```

### 責務
- API routing
- multimodal IO
- model abstraction
- execution coordination

### 位置付け
```text
AI communication bus
```

---

# Replay Engine の位置付け

## 基本定義

Replayとは：

```text
event fact を意味空間へ投影する層
```

である。

---

## Event Store
```text
事実
```

---

## Replay
```text
事実の解釈
```

---

## TVKB
```text
意味記憶化
```

---

## MED
```text
意味空間最適化
```

---

# Replay Plugin化

## 方針

Replay Engine自体をplugin化する。

理由：

```text
同じeventでも、
何を意味として見るかが異なる
```

ため。

---

## Replay Plugin例

### Session Replay
```text
会話として再構築
```

### Topic Replay
```text
topic遷移として再構築
```

### Temporal Replay
```text
時間窓として再構築
```

### Semantic Replay
```text
embedding clusterとして再構築
```

### Agent Replay
```text
agent行動として再構築
```

---

# Event Store と Replay の責務分離

## 不変層
```text
Internal Event Schema
Event Store(JSONL)
```

---

## 可変層
```text
Replay
Topic Graph
Summary
GUI Projection
Semantic Projection
```

---

# Snapshot Metadata 構想

## Snapshot定義

Snapshotは：

```text
保存済みReplay状態
```

である。

---

## Metadata例

```json
{
  "snapshot_id": "...",
  "created_at": "...",

  "event_range": {
    "start": 1000,
    "end": 2200
  },

  "session_chunks": [],

  "context_window": {
    "messages": 320,
    "tokens_estimated": 48000
  },

  "topics": [],

  "umap_projection_ref": "...",

  "summary_refs": [],

  "delta_from": "..."
}
```

---

# Event Store Rotation

## 方針
```text
session + chunk
```

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

## 役割分離

### Event Store
```text
append efficiency
```

### Replay
```text
意味単位への再分割
```

---

# Conversation Indexing Pipeline

## 目的

chunkを：

```text
会話単位
```

へ再分割する。

---

## 想定処理

### 1. session chunk再分割
- 会話境界検出
- DB索引生成
- 最新会話追跡
- 過去会話参照

---

### 2. 要約生成

粒度：

```text
message
conversation
topic
```

---

### 3. Snapshot / Delta連携

- chunk末尾追跡
- 差分Replay
- incremental rebuild

---

# GUI の位置付け

GUIは：

```text
semantic viewport
```

である。

---

# Session参照処理

## 最新会話追従
- 最新conversationロード
- 過去会話遡り
- chunk横断参照

---

## Topic追従

### 初期方式
```text
moving average
```

### 将来候補
- weighted aggregation
- graph-based importance
- semantic continuity scoring

---

# UMAP 地図構想

## Pipeline

```text
Event
 ↓
Replay
 ↓
Embedding
 ↓
UMAP Projection
 ↓
Map GUI
```

---

## 可視化候補

### source別色分け
- Claude CLI
- WebChat
- Discord
- Gemini

---

### session別色分け
```text
どこで何に近い話をしているか
```

---

### 時間窓可視化
```text
いつどんなtopicを話していたか
```

---

# 現時点の全体構造

```text
                AIHub
                   │
      ┌────────────┼────────────┐
      │            │            │
   Claude       WebChat      Other
      │            │
      └─────Adapter Layer─────┘
                   │
         Internal Event Schema
                   │
              Event Store
                   │
          Replay Plugin Layer
                   │
        ┌──────────┼──────────┐
        │          │          │
      TVKB       GUI        MED
        │                     │
        └──── Semantic Space ─┘
```

---

# 現時点での重要設計思想

## 固定するもの
```text
Event facts
Internal schema
Append-only store
```

---

## 交換可能にするもの
```text
Replay
Topic projection
Semantic interpretation
Summary
Visualization
```

---

# 今後の優先実装

## Core
- Internal Event Schema v1
- Claude Adapter
- Hook Schema Extractor
- JSONL Event Store
- Replay Plugin Interface

---

## Replay Layer
- conversation indexing
- delta replay
- snapshot metadata
- topic aggregation

---

## Semantic Layer
- topic graph
- embedding integration
- TVKB linkage
- MED integration

---

## GUI
- session explorer
- semantic timeline
- topic visualization
- UMAP map
