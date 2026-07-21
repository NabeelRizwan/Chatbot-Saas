"use client";

import { useEffect, useState, useRef } from "react";
import { 
  Search, CheckCircle, HelpCircle, Archive, 
  MessageSquare, Clock, Download, X, Database,
  Pin, PinOff, Trash2, Edit3, Share2, Copy,
  ExternalLink, FileText, Check, FolderArchive,
  RefreshCw, ArchiveRestore
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { getBots } from "@/services/bot-service";
import { useAuthStore } from "@/store/auth-store";
import { useToastStore } from "@/store/toast-store";
import type { Bot as BotType } from "@/types/bot";
import { API_BASE_URL } from "@/services/api";

interface Session {
  id: number;
  bot_id: number;
  bot_name: string;
  organization_id: number;
  session_id: string;
  title: string;
  is_pinned: boolean;
  is_archived: boolean;
  shared_token: string | null;
  channel: string;
  status: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

interface Message {
  id: number;
  user_message: string;
  assistant_response: string;
  response_time_ms: number;
  status: string;
  is_fallback: boolean;
  had_knowledge_hit: boolean;
  created_at: string;
}

export function InboxClient() {
  const selectedOrganizationId = useAuthStore((state) => state.selectedOrganizationId);
  const accessToken = useAuthStore((state) => state.accessToken);
  const showToast = useToastStore((state) => state.showToast);

  const [bots, setBots] = useState<BotType[]>([]);
  const [conversations, setConversations] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<{ session: Session; messages: Message[] } | null>(null);
  
  // Filters & Sorting
  const [statusFilter, setStatusFilter] = useState<string>("open");
  const [searchQuery, setSearchQuery] = useState("");
  const [botFilter, setBotFilter] = useState("");
  const [tagFilter] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [sortBy, setSortBy] = useState<"activity" | "date">("activity");

  // Interaction States
  const [newTagText, setNewTagText] = useState("");
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingActive, setLoadingActive] = useState(false);
  const [sharing, setSharing] = useState(false);

  const timelineEndRef = useRef<HTMLDivElement>(null);

  // Load initial bots
  useEffect(() => {
    async function loadBots() {
      try {
        const list = await getBots();
        setBots(list);
      } catch (err) {
        console.error("Error loading bots:", err);
      }
    }
    if (selectedOrganizationId) {
      void loadBots();
    }
  }, [selectedOrganizationId]);

  // Load conversations based on filters
  const fetchConversations = async () => {
    if (!selectedOrganizationId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.append("status", statusFilter);
      if (botFilter) params.append("bot_id", botFilter);
      if (tagFilter) params.append("tag", tagFilter);
      if (searchQuery) params.append("search", searchQuery);
      params.append("include_archived", includeArchived ? "true" : "false");
      params.append("sort_by", sortBy);

      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations?${params.toString()}`,
        {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      if (res.ok) {
        const data = await res.json();
        setConversations(data);
      }
    } catch (err) {
      console.error("Error fetching conversations:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchConversations();
  }, [selectedOrganizationId, statusFilter, botFilter, tagFilter, searchQuery, includeArchived, sortBy]);

  // Load details for the selected session
  const fetchActiveSession = async (sessId: string) => {
    if (!selectedOrganizationId) return;
    setLoadingActive(true);
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${sessId}`,
        {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      if (res.ok) {
        const data = await res.json();
        setActiveSession(data);
        setTimeout(() => scrollToBottom(), 50);
      }
    } catch (err) {
      console.error("Error loading session details:", err);
    } finally {
      setLoadingActive(false);
    }
  };

  useEffect(() => {
    if (selectedSessionId) {
      void fetchActiveSession(selectedSessionId);
    } else {
      setActiveSession(null);
    }
  }, [selectedSessionId]);

  const scrollToBottom = () => {
    timelineEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Update session status (e.g. resolved vs open)
  const updateSessionStatus = async (newStatus: string) => {
    if (!selectedOrganizationId || !selectedSessionId || !activeSession) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${selectedSessionId}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ status: newStatus }),
        }
      );
      if (res.ok) {
        showToast({
          title: "Status updated",
          description: `Conversation marked as ${newStatus}.`,
          variant: "success"
        });
        await fetchActiveSession(selectedSessionId);
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error updating status:", err);
    }
  };

  // Toggle Pinned
  const togglePin = async (session: Session) => {
    if (!selectedOrganizationId) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${session.session_id}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ is_pinned: !session.is_pinned }),
        }
      );
      if (res.ok) {
        showToast({
          title: session.is_pinned ? "Conversation unpinned" : "Conversation pinned",
          description: session.is_pinned ? "Thread has been unpinned from top." : "Thread has been pinned to the top.",
          variant: "success"
        });
        if (selectedSessionId === session.session_id) {
          await fetchActiveSession(session.session_id);
        }
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error pinning session:", err);
    }
  };

  // Toggle Archived
  const toggleArchive = async (session: Session) => {
    if (!selectedOrganizationId) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${session.session_id}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ is_archived: !session.is_archived }),
        }
      );
      if (res.ok) {
        showToast({
          title: session.is_archived ? "Conversation unarchived" : "Conversation archived",
          description: session.is_archived ? "Thread restored to active list." : "Thread moved to archive.",
          variant: "success"
        });
        if (selectedSessionId === session.session_id) {
          setSelectedSessionId(null);
          setActiveSession(null);
        }
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error archiving session:", err);
    }
  };

  // Rename Session
  const saveRename = async (session_id: string) => {
    if (!selectedOrganizationId || !renameValue.trim()) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${session_id}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ title: renameValue.trim() }),
        }
      );
      if (res.ok) {
        setRenamingSessionId(null);
        setRenameValue("");
        showToast({
          title: "Rename successful",
          description: "Conversation thread renamed.",
          variant: "success"
        });
        if (selectedSessionId === session_id) {
          await fetchActiveSession(session_id);
        }
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error renaming session:", err);
    }
  };

  // Delete Session
  const deleteConversation = async (session: Session) => {
    if (!selectedOrganizationId) return;
    if (!confirm("Are you sure you want to permanently delete this conversation and all its messages?")) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${session.session_id}`,
        {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      if (res.ok) {
        showToast({
          title: "Conversation deleted",
          description: "The thread has been permanently removed.",
          variant: "success"
        });
        if (selectedSessionId === session.session_id) {
          setSelectedSessionId(null);
          setActiveSession(null);
        }
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error deleting session:", err);
    }
  };

  // Duplicate Conversation
  const duplicateConversation = async () => {
    if (!selectedOrganizationId || !selectedSessionId) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${selectedSessionId}/duplicate`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      if (res.ok) {
        const data = await res.json();
        showToast({
          title: "Conversation duplicated",
          description: `Duplicated into a new thread: ${data.title}`,
          variant: "success"
        });
        setSelectedSessionId(data.session_id);
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error duplicating conversation:", err);
    }
  };

  // Share Conversation Link
  const shareConversation = async () => {
    if (!selectedOrganizationId || !selectedSessionId) return;
    setSharing(true);
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${selectedSessionId}/share`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      if (res.ok) {
        const data = await res.json();
        // Construct public share URL
        const shareUrl = `${window.location.origin}/public/share/${data.shared_token}`;
        await navigator.clipboard.writeText(shareUrl);
        showToast({
          title: "Link copied!",
          description: "Public read-only link copied to clipboard.",
          variant: "success"
        });
        await fetchActiveSession(selectedSessionId);
      }
    } catch (err) {
      console.error("Error sharing conversation:", err);
    } finally {
      setSharing(false);
    }
  };

  // Unshare Conversation
  const unshareConversation = async () => {
    if (!selectedOrganizationId || !selectedSessionId) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${selectedSessionId}/unshare`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      if (res.ok) {
        showToast({
          title: "Sharing disabled",
          description: "Public link has been revoked.",
          variant: "success"
        });
        await fetchActiveSession(selectedSessionId);
      }
    } catch (err) {
      console.error("Error unsharing conversation:", err);
    }
  };

  // Add tag
  const addTag = async () => {
    if (!selectedOrganizationId || !selectedSessionId || !activeSession || !newTagText.trim()) return;
    const currentTags = activeSession.session.tags || [];
    if (currentTags.includes(newTagText.trim())) return;
    
    const updatedTags = [...currentTags, newTagText.trim()];
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${selectedSessionId}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ tags: updatedTags }),
        }
      );
      if (res.ok) {
        setNewTagText("");
        await fetchActiveSession(selectedSessionId);
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error adding tag:", err);
    }
  };

  // Remove tag
  const removeTag = async (tagToRemove: string) => {
    if (!selectedOrganizationId || !selectedSessionId || !activeSession) return;
    const currentTags = activeSession.session.tags || [];
    const updatedTags = currentTags.filter((t) => t !== tagToRemove);
    try {
      const res = await fetch(
        `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/${selectedSessionId}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ tags: updatedTags }),
        }
      );
      if (res.ok) {
        await fetchActiveSession(selectedSessionId);
        await fetchConversations();
      }
    } catch (err) {
      console.error("Error removing tag:", err);
    }
  };

  // Export Markdown
  const exportMarkdown = () => {
    if (!activeSession) return;
    let md = `# Conversation Transcript: ${activeSession.session.title}\n`;
    md += `*Bot Name:* ${activeSession.session.bot_name}\n`;
    md += `*Session ID:* ${activeSession.session.session_id}\n`;
    md += `*Date:* ${new Date(activeSession.session.created_at).toLocaleString()}\n`;
    md += `---\n\n`;

    activeSession.messages.forEach((m) => {
      if (m.user_message) {
        md += `**User:** ${m.user_message}\n\n`;
      }
      md += `**${activeSession.session.bot_name}:** ${m.assistant_response || (m.status === "error" ? "[Message failed]" : "[Generating...]")}\n\n`;
    });

    const blob = new Blob([md], { type: "text/markdown;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `transcript_${activeSession.session.session_id.substring(0, 8)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  // Export PDF
  const exportPDF = () => {
    if (!activeSession) return;
    // Create printing template in a new window
    const printWindow = window.open("", "_blank");
    if (!printWindow) return;

    let html = `
      <html>
        <head>
          <title>Transcript - ${activeSession.session.title}</title>
          <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 40px; color: #1e293b; max-width: 800px; margin: 0 auto; line-height: 1.6; }
            h1 { font-size: 24px; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin-bottom: 5px; }
            .meta { color: #64748b; font-size: 13px; margin-bottom: 40px; }
            .message { margin-bottom: 25px; }
            .user { font-weight: bold; color: #2563eb; }
            .bot { font-weight: bold; color: #0f172a; }
            .content { margin-top: 5px; padding-left: 15px; border-left: 3px solid #e2e8f0; white-space: pre-wrap; font-size: 14px; }
          </style>
        </head>
        <body>
          <h1>Transcript: ${activeSession.session.title}</h1>
          <div class="meta">
            <strong>Bot:</strong> ${activeSession.session.bot_name} | 
            <strong>Created:</strong> ${new Date(activeSession.session.created_at).toLocaleString()} | 
            <strong>Session ID:</strong> ${activeSession.session.session_id}
          </div>
    `;

    activeSession.messages.forEach((m) => {
      if (m.user_message) {
        html += `
          <div class="message">
            <span class="user">User</span>
            <div class="content">${m.user_message}</div>
          </div>
        `;
      }
      html += `
        <div class="message">
          <span class="bot">${activeSession.session.bot_name}</span>
          <div class="content">${m.assistant_response || "[No response]"}</div>
        </div>
      `;
    });

    html += `
          <script>
            window.onload = function() { window.print(); window.close(); }
          </script>
        </body>
      </html>
    `;

    printWindow.document.write(html);
    printWindow.document.close();
  };

  // Trigger JSON/CSV Export
  const triggerExport = (format: "json" | "csv") => {
    if (!selectedOrganizationId) return;
    const exportUrl = `${API_BASE_URL}/organizations/${selectedOrganizationId}/conversations/export?format=${format}`;
    
    const link = document.createElement("a");
    link.href = exportUrl;
    link.target = "_blank";
    link.download = `conversations_org_${selectedOrganizationId}.${format}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Group messages by date
  const groupMessagesByDate = (msgs: Message[]) => {
    const groups: { [key: string]: Message[] } = {};
    msgs.forEach((m) => {
      const date = new Date(m.created_at);
      const dateStr = date.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
      if (!groups[dateStr]) {
        groups[dateStr] = [];
      }
      groups[dateStr].push(m);
    });
    return groups;
  };

  return (
    <div className="flex h-[calc(100vh-140px)] min-h-[550px] overflow-hidden rounded-2xl border border-border bg-card shadow-lg transition-all duration-300">
      
      {/* Pane 1: Conversations List */}
      <div className="flex w-80 flex-col border-r border-border bg-muted/10">
        
        {/* Filters and Header */}
        <div className="space-y-3 p-4 border-b border-border bg-card/50">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold tracking-tight text-foreground">Conversations</h2>
            
            {/* Filter buttons */}
            <div className="flex gap-1">
              <Button 
                size="icon" 
                variant={statusFilter === "open" ? "default" : "outline"} 
                className="h-7 w-7 rounded-lg"
                onClick={() => setStatusFilter("open")}
                title="View Open"
              >
                <MessageSquare className="h-3.5 w-3.5" />
              </Button>
              <Button 
                size="icon" 
                variant={statusFilter === "resolved" ? "default" : "outline"} 
                className="h-7 w-7 rounded-lg"
                onClick={() => setStatusFilter("resolved")}
                title="View Resolved"
              >
                <CheckCircle className="h-3.5 w-3.5" />
              </Button>
              <Button 
                size="icon" 
                variant={includeArchived ? "default" : "outline"} 
                className="h-7 w-7 rounded-lg text-amber-500 border-amber-200/50 hover:bg-amber-500/10"
                onClick={() => setIncludeArchived(!includeArchived)}
                title="View Archived"
              >
                <FolderArchive className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search conversations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-9 w-full rounded-lg border border-input bg-card pl-8 pr-3 text-xs outline-none focus:ring-2 focus:ring-primary/20 transition-all"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <select
              value={botFilter}
              onChange={(e) => setBotFilter(e.target.value)}
              className="h-8 rounded-lg border border-input bg-card px-2 text-2xs outline-none focus:ring-1 focus:ring-primary/20 cursor-pointer"
            >
              <option value="">All Bots</option>
              {bots.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>

            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as "activity" | "date")}
              className="h-8 rounded-lg border border-input bg-card px-2 text-2xs outline-none focus:ring-1 focus:ring-primary/20 cursor-pointer"
            >
              <option value="activity">Recent Activity</option>
              <option value="date">Date Created</option>
            </select>
          </div>
        </div>

        {/* Scrollable list */}
        <div className="flex-1 overflow-y-auto divide-y divide-border">
          {loading ? (
            <div className="flex flex-col items-center justify-center p-8 gap-2 text-xs text-muted-foreground">
              <RefreshCw className="h-5 w-5 animate-spin" />
              Loading threads...
            </div>
          ) : conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
              <Archive className="h-8 w-8 mb-2 opacity-30" />
              <p className="text-xs font-semibold">No threads found</p>
              <p className="text-2xs opacity-70 mt-1">Try refining filters or search queries.</p>
            </div>
          ) : (
            conversations.map((sess) => {
              const active = selectedSessionId === sess.session_id;
              const dateStr = new Date(sess.updated_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              });
              
              const displayName = sess.title || `Chat ${sess.session_id.substring(0, 8)}`;
              
              return (
                <div
                  key={sess.id}
                  className={`w-full group text-left p-3 hover:bg-muted/30 transition-all flex flex-col gap-1.5 relative border-l-2 ${
                    active ? "bg-primary/5 border-primary" : "border-transparent"
                  }`}
                >
                  <div className="flex items-center justify-between w-full">
                    {renamingSessionId === sess.session_id ? (
                      <div className="flex items-center gap-1 w-[80%]">
                        <input
                          type="text"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void saveRename(sess.session_id);
                          }}
                          className="h-6 w-full rounded border bg-background px-1 text-[11px] outline-none"
                          autoFocus
                        />
                        <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => void saveRename(sess.session_id)}>
                          <Check className="h-3 w-3 text-emerald-600" />
                        </Button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setSelectedSessionId(sess.session_id)}
                        className="font-bold text-xs tracking-tight text-foreground truncate max-w-[150px] text-left hover:underline"
                      >
                        {displayName}
                      </button>
                    )}
                    
                    {/* Action buttons (always visible on hover, or when active) */}
                    <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity bg-transparent">
                      <button 
                        onClick={() => togglePin(sess)} 
                        className={`p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground`}
                        title={sess.is_pinned ? "Unpin" : "Pin thread"}
                      >
                        {sess.is_pinned ? <PinOff className="h-3 w-3 text-primary" /> : <Pin className="h-3 w-3" />}
                      </button>
                      <button 
                        onClick={() => {
                          setRenamingSessionId(sess.session_id);
                          setRenameValue(sess.title || "");
                        }}
                        className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
                        title="Rename"
                      >
                        <Edit3 className="h-3 w-3" />
                      </button>
                      <button 
                        onClick={() => toggleArchive(sess)} 
                        className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-amber-600"
                        title={sess.is_archived ? "Unarchive" : "Archive"}
                      >
                        {sess.is_archived ? <ArchiveRestore className="h-3 w-3" /> : <Archive className="h-3 w-3" />}
                      </button>
                      <button 
                        onClick={() => deleteConversation(sess)} 
                        className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-destructive"
                        title="Delete"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                  
                  <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                    <span className="truncate max-w-[120px]">{sess.bot_name}</span>
                    <span>{dateStr}</span>
                  </div>

                  {sess.tags && sess.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {sess.tags.map((t) => (
                        <span key={t} className="bg-primary/10 text-primary text-[8px] font-semibold px-1.5 py-0.5 rounded-md">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
      
      {/* Pane 2: Conversation View */}
      <div className="flex-1 flex flex-col min-w-[380px] bg-muted/5">
        {loadingActive ? (
          <div className="flex-1 flex flex-col items-center justify-center text-xs text-muted-foreground gap-2">
            <RefreshCw className="h-6 w-6 animate-spin text-primary" />
            Loading conversation timeline...
          </div>
        ) : !activeSession ? (
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center text-muted-foreground">
            <MessageSquare className="h-14 w-14 mb-4 text-primary opacity-30 animate-pulse" />
            <h3 className="text-base font-bold text-foreground">Open a chat thread</h3>
            <p className="text-xs max-w-xs mt-2 opacity-80">
              Select a conversation from the list to view transcripts, export data, manage tags, or test custom AI configurations.
            </p>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="p-4 border-b border-border flex items-center justify-between bg-card shadow-sm z-10">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-foreground">{activeSession.session.title || "Active Transcript"}</h3>
                  {activeSession.session.is_pinned && (
                    <span className="bg-primary/10 text-primary text-[9px] px-1.5 py-0.5 rounded-full flex items-center gap-0.5 font-semibold">
                      <Pin className="h-2.5 w-2.5 fill-primary" /> Pinned
                    </span>
                  )}
                </div>
                <p className="text-2xs text-muted-foreground">Session: {activeSession.session.session_id}</p>
              </div>
              <div className="flex gap-2">
                <Button 
                  size="sm" 
                  variant="outline" 
                  onClick={duplicateConversation}
                  className="h-8 text-xs gap-1 border-border bg-card hover:bg-muted"
                >
                  <Copy className="h-3.5 w-3.5" />
                  Duplicate
                </Button>
                
                {activeSession.session.status === "resolved" ? (
                  <Button 
                    size="sm" 
                    variant="outline" 
                    onClick={() => void updateSessionStatus("open")}
                    className="h-8 gap-1.5 text-xs text-amber-600 border-amber-200 bg-amber-50 hover:bg-amber-100"
                  >
                    Reopen Chat
                  </Button>
                ) : (
                  <Button 
                    size="sm" 
                    onClick={() => void updateSessionStatus("resolved")}
                    className="h-8 gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                  >
                    <CheckCircle className="h-3.5 w-3.5" />
                    Resolve Inquiry
                  </Button>
                )}
              </div>
            </div>

            {/* Timeline Messages */}
            <div className="flex-1 overflow-y-auto p-5 space-y-6">
              {Object.entries(groupMessagesByDate(activeSession.messages)).map(([date, msgs]) => (
                <div key={date} className="space-y-4">
                  {/* Date Divider */}
                  <div className="flex items-center justify-center my-4">
                    <span className="bg-muted px-3 py-1 rounded-full text-[10px] font-bold text-muted-foreground shadow-sm">
                      {date}
                    </span>
                  </div>

                  {msgs.map((m) => {
                    const messageTime = new Date(m.created_at).toLocaleTimeString(undefined, {
                      hour: 'numeric',
                      minute: '2-digit'
                    });
                    
                    return (
                      <div key={m.id} className="space-y-2">
                        {/* User message block */}
                        {m.user_message && (
                          <div className="flex justify-end gap-2.5">
                            <div className="max-w-[75%] bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-2.5 text-xs shadow-md leading-relaxed">
                              <p className="whitespace-pre-wrap">{m.user_message}</p>
                              <div className="text-right mt-1 text-[8px] opacity-70">{messageTime}</div>
                            </div>
                            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary font-bold text-2xs uppercase">
                              U
                            </div>
                          </div>
                        )}

                        {/* Assistant response block */}
                        <div className="flex justify-start gap-2.5">
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-800 font-bold text-2xs uppercase">
                            AI
                          </div>
                          <div className="max-w-[75%] bg-card border border-border rounded-2xl rounded-tl-sm px-4 py-3 text-xs shadow-md space-y-2 relative">
                            <p className="leading-relaxed text-foreground whitespace-pre-wrap">
                              {m.assistant_response || (m.status === "error" ? "Message delivery failed." : "Generating...")}
                            </p>
                            
                            {/* Latency & Hit info */}
                            <div className="flex items-center justify-between text-[9px] text-muted-foreground border-t border-dashed border-border pt-2 mt-2">
                              <div className="flex items-center gap-3">
                                <span className="flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  {m.response_time_ms ? `${(m.response_time_ms / 1000).toFixed(2)}s` : "N/A"}
                                </span>
                                
                                {m.had_knowledge_hit && (
                                  <span className="flex items-center gap-0.5 text-emerald-600 font-semibold bg-emerald-50 px-1 rounded-md">
                                    <Database className="h-2.5 w-2.5" />
                                    RAG Hit
                                  </span>
                                )}

                                {m.is_fallback && (
                                  <span className="flex items-center gap-0.5 text-amber-600 font-semibold bg-amber-50 px-1 rounded-md">
                                    <HelpCircle className="h-2.5 w-2.5" />
                                    Fallback
                                  </span>
                                )}
                              </div>
                              
                              <span className="opacity-70">{messageTime}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
              <div ref={timelineEndRef} />
            </div>
          </>
        )}
      </div>

      {/* Pane 3: Chat Sidebar Details */}
      {activeSession && (
        <div className="w-64 border-l border-border p-4 bg-card overflow-y-auto space-y-5 z-10 shadow-sm">
          <div>
            <h4 className="text-2xs font-bold text-muted-foreground uppercase tracking-widest mb-3">Session Details</h4>
            <div className="space-y-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Bot Name:</span>
                <span className="font-semibold truncate max-w-[125px]">{activeSession.session.bot_name}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Status:</span>
                <span className={`px-2 py-0.5 rounded-md text-[9px] font-bold uppercase ${
                  activeSession.session.status === "resolved" ? "bg-emerald-100 text-emerald-800" : "bg-blue-100 text-blue-800"
                }`}>
                  {activeSession.session.status || "open"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Created:</span>
                <span className="font-medium">{new Date(activeSession.session.created_at).toLocaleDateString()}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Channel:</span>
                <span className="capitalize font-medium">{activeSession.session.channel}</span>
              </div>
            </div>
          </div>

          <hr className="border-border" />

          {/* Share Transcripts */}
          <div>
            <h4 className="text-2xs font-bold text-muted-foreground uppercase tracking-widest mb-3">Public Sharing</h4>
            {activeSession.session.shared_token ? (
              <div className="space-y-3">
                <div className="rounded-lg bg-emerald-50 border border-emerald-100 p-2 text-2xs text-emerald-800 flex items-center justify-between">
                  <span className="truncate max-w-[150px]">Link is active</span>
                  <ExternalLink 
                    className="h-3 w-3 cursor-pointer text-emerald-600 hover:text-emerald-800" 
                    onClick={() => window.open(`/public/share/${activeSession.session.shared_token}`, '_blank')}
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button size="sm" variant="outline" className="h-8 text-2xs gap-1.5" onClick={shareConversation}>
                    <Copy className="h-3 w-3" /> Recopy
                  </Button>
                  <Button size="sm" variant="outline" className="h-8 text-2xs text-destructive hover:bg-destructive/5" onClick={unshareConversation}>
                    <X className="h-3 w-3" /> Disable
                  </Button>
                </div>
              </div>
            ) : (
              <Button size="sm" className="w-full h-8 text-2xs gap-1.5 bg-primary hover:bg-primary/95 text-primary-foreground" onClick={shareConversation} disabled={sharing}>
                <Share2 className="h-3.5 w-3.5" />
                {sharing ? "Generating..." : "Generate Public Link"}
              </Button>
            )}
          </div>

          <hr className="border-border" />

          {/* Tags Manager */}
          <div>
            <h4 className="text-2xs font-bold text-muted-foreground uppercase tracking-widest mb-3">Tags & Labels</h4>
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(activeSession.session.tags || []).length === 0 ? (
                <p className="text-[10px] text-muted-foreground italic">No tags applied.</p>
              ) : (
                activeSession.session.tags.map((tag) => (
                  <span key={tag} className="flex items-center gap-1 bg-muted px-2 py-0.5 rounded text-[10px] font-medium text-foreground border border-border">
                    {tag}
                    <button onClick={() => void removeTag(tag)} className="text-muted-foreground hover:text-destructive">
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </span>
                ))
              )}
            </div>
            
            <div className="flex gap-1.5">
              <input
                type="text"
                placeholder="New label..."
                value={newTagText}
                onChange={(e) => setNewTagText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void addTag();
                }}
                className="h-8 min-w-0 flex-1 rounded-lg border border-input px-2 text-xs outline-none focus:ring-2 focus:ring-primary/10 transition-all"
              />
              <Button size="sm" onClick={() => void addTag()} className="h-8">Add</Button>
            </div>
          </div>

          <hr className="border-border" />

          {/* Export tools */}
          <div>
            <h4 className="text-2xs font-bold text-muted-foreground uppercase tracking-widest mb-3">Export Data</h4>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <Button size="sm" variant="outline" onClick={exportMarkdown} className="h-8 text-2xs gap-1">
                <FileText className="h-3 w-3" /> Markdown
              </Button>
              <Button size="sm" variant="outline" onClick={exportPDF} className="h-8 text-2xs gap-1">
                <Download className="h-3 w-3" /> PDF Report
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button size="sm" variant="outline" onClick={() => triggerExport("json")} className="h-8 text-2xs gap-1">
                <Download className="h-3 w-3" /> JSON Dump
              </Button>
              <Button size="sm" variant="outline" onClick={() => triggerExport("csv")} className="h-8 text-2xs gap-1">
                <Download className="h-3 w-3" /> CSV Table
              </Button>
            </div>
          </div>

        </div>
      )}

    </div>
  );
}
