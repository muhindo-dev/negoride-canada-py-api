import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiChevronLeft, FiChevronRight, FiSearch, FiArrowLeft, FiMessageSquare, FiAlertTriangle } from 'react-icons/fi';

export default function ChatsPage() {
  const [heads, setHeads] = useState([]);
  const [messages, setMessages] = useState([]);
  const [selectedChat, setSelectedChat] = useState(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [msgLoading, setMsgLoading] = useState(false);
  const [error, setError] = useState(null);
  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const loadHeads = (p = page) => {
    setLoading(true); setError(null);
    adminAPI.chats({ page: p, per_page: perPage })
      .then(({ data }) => {
        if (data.code === 1) { setHeads(data.data?.data || []); setTotal(data.data?.total || 0); }
        else setError(data.message || 'Failed to load');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  const loadMessages = chatId => {
    setMsgLoading(true);
    adminAPI.chatMessages(chatId)
      .then(({ data }) => { if (data.code === 1) setMessages(data.data || []); })
      .catch(() => {})
      .finally(() => setMsgLoading(false));
  };

  useEffect(() => { loadHeads(1); }, []);

  const openChat = chat => {
    setSelectedChat(chat);
    setMessages([]);
    loadMessages(chat.id);
  };

  const filteredHeads = search.trim()
    ? heads.filter(h => {
        const q = search.toLowerCase();
        return (h.product_owner_name || '').toLowerCase().includes(q)
          || (h.customer_name || '').toLowerCase().includes(q)
          || (h.last_message_body || '').toLowerCase().includes(q);
      })
    : heads;

  /* ── Message View ── */
  if (selectedChat) {
    return (
      <div className="page-chats">
        <div className="page-toolbar">
          <button className="btn btn-sm" onClick={() => { setSelectedChat(null); setMessages([]); }}>
            <FiArrowLeft /> Back to Chats
          </button>
          <span className="toolbar-info" style={{ flex: 1, textAlign: 'center' }}>
            <FiMessageSquare style={{ marginRight: 6 }} />
            {selectedChat.product_owner_name || 'Driver'} ↔ {selectedChat.customer_name || 'Passenger'}
            &nbsp;&nbsp;—&nbsp;&nbsp;Chat #{selectedChat.id}
          </span>
          <span className="toolbar-info">{messages.length} messages</span>
        </div>

        {msgLoading ? <div className="page-loader">Loading messages…</div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '8px 0', maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' }}>
            {messages.length ? messages.map(m => {
              const isOwner = m.sender_id === selectedChat.product_owner_id;
              return (
                <div key={m.id} style={{
                  display: 'flex', justifyContent: isOwner ? 'flex-end' : 'flex-start',
                  padding: '0 16px',
                }}>
                  <div style={{
                    maxWidth: '68%', background: isOwner ? 'var(--accent-light)' : 'var(--bg-secondary)',
                    border: `1px solid ${isOwner ? 'rgba(239,155,17,.3)' : 'var(--grey-10)'}`,
                    padding: '10px 14px', fontSize: 13,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 4 }}>
                      <strong style={{ fontSize: 12 }}>{m.sender_name || `User #${m.sender_id}`}</strong>
                      <small style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>{m.created_at?.slice(0, 16)}</small>
                    </div>
                    <div>{m.body || <em style={{ color: 'var(--text-tertiary)' }}>[{m.type || 'media'}]</em>}</div>
                  </div>
                </div>
              );
            }) : <p className="empty-state">No messages in this conversation</p>}
          </div>
        )}
      </div>
    );
  }

  /* ── Chat List ── */
  return (
    <div className="page-chats">
      <div className="page-toolbar">
        <form onSubmit={e => e.preventDefault()} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Filter by participant name or message…" value={search} onChange={e => setSearch(e.target.value)} />
        </form>
        <span className="toolbar-info">{total} conversations</span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={() => loadHeads()} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>Driver / Owner</th><th>Passenger</th><th>Last Message</th><th>Messages</th><th>Updated</th><th></th></tr>
            </thead>
            <tbody>
              {filteredHeads.map(h => (
                <tr key={h.id}>
                  <td style={{ fontWeight: 700 }}>#{h.id}</td>
                  <td>{h.product_owner_name || `#${h.product_owner_id}`}</td>
                  <td>{h.customer_name || `#${h.customer_id}`}</td>
                  <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)', fontSize: 12 }}>
                    {h.last_message_body || <em>No messages yet</em>}
                  </td>
                  <td><span className="badge">{h.message_count ?? 0}</span></td>
                  <td>{h.updated_at?.slice(0, 10)}</td>
                  <td>
                    <button className="btn btn-xs btn-accent" onClick={() => openChat(h)}><FiMessageSquare /> View</button>
                  </td>
                </tr>
              ))}
              {!filteredHeads.length && <tr><td colSpan="7" className="empty-state">No conversations found</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => { const p = page - 1; setPage(p); loadHeads(p); }}><FiChevronLeft /></button>
          <span>Page {page} of {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => { const p = page + 1; setPage(p); loadHeads(p); }}><FiChevronRight /></button>
        </div>
      )}
    </div>
  );
}
