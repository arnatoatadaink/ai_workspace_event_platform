import { ConversationPane } from "./ConversationPane";
import { MessageDetail } from "./MessageDetail";
import { TopicPane } from "./TopicPane";

interface Props {
  sessionId: string | null;
  onClose: () => void;
}

export function DetailSidebar({ sessionId, onClose }: Props) {
  return (
    <aside className="detail-sidebar">
      <div className="detail-sidebar-header">
        <span className="detail-sidebar-title">Detail</span>
        <button className="detail-sidebar-close" onClick={onClose} title="サイドバーを閉じる">
          ✕
        </button>
      </div>
      <div className="sidebar-section sidebar-section--topics">
        <TopicPane sessionId={sessionId} />
      </div>
      <div className="sidebar-section sidebar-section--conv">
        <ConversationPane sessionId={sessionId} />
      </div>
      <div className="sidebar-section sidebar-section--events">
        <MessageDetail sessionId={sessionId} />
      </div>
    </aside>
  );
}
