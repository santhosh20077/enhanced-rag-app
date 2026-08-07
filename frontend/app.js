document.addEventListener('DOMContentLoaded', () => {
  // =========================================================
  //  ELEMENT REFERENCES
  // =========================================================
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const statusBadge = document.getElementById('status-badge');
  const chunksCount = document.getElementById('chunks-count');
  const avgChunkSize = document.getElementById('avg-chunk-size');
  const indexTime = document.getElementById('index-time');
  const fileList = document.getElementById('file-list');
  const fileSearchWrapper = document.getElementById('file-search-wrapper');
  const fileSearchInput = document.getElementById('file-search-input');
  const clearBtn = document.getElementById('clear-btn');
  const chatMessages = document.getElementById('chat-messages');
  const chatInput = document.getElementById('chat-input');
  const sendBtn = document.getElementById('send-btn');
  const scrollToBottomBtn = document.getElementById('scroll-to-bottom-btn');
  const sidebar = document.getElementById('sidebar');
  const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
  const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
  const sidebarOverlay = document.getElementById('sidebar-overlay');
  const themeToggleBtn = document.getElementById('theme-toggle-btn');
  const eli5Toggle = document.getElementById('eli5-toggle');
  const exportChatBtn = document.getElementById('export-chat-btn');
  const voiceInputBtn = document.getElementById('voice-input-btn');
  const toastContainer = document.getElementById('toast-container');
  const soundToggleBtn = document.getElementById('sound-toggle-btn');
  const chatHistoryToggle = document.getElementById('chat-history-toggle');
  const chatHistoryBody = document.getElementById('chat-history-body');
  const chatHistoryPanel = chatHistoryToggle?.closest('.chat-history-panel');
  const newSessionBtn = document.getElementById('new-session-btn');
  const sessionListEl = document.getElementById('session-list');

  // Auth Elements
  const authLoggedOut = document.getElementById('auth-logged-out');
  const authLoggedIn = document.getElementById('auth-logged-in');
  const demoLoginBtn = document.getElementById('demo-login-btn');
  const signoutBtn = document.getElementById('signout-btn');
  const userAvatarImg = document.getElementById('user-avatar-img');
  const userAvatarFallback = document.getElementById('user-avatar-fallback');
  const userDisplayName = document.getElementById('user-display-name');
  const userDisplayEmail = document.getElementById('user-display-email');
  const identityGate = document.getElementById('identity-gate');
  const identitySigninBtn = document.getElementById('identity-signin-btn');
  const identityGuestBtn = document.getElementById('identity-guest-btn');

  // =========================================================
  //  CONFIGURE MARKED.JS + HIGHLIGHT.JS
  // =========================================================
  if (window.marked) {
    marked.setOptions({
      breaks: true,
      gfm: true,
      highlight: function(code, lang) {
        if (window.hljs && lang && hljs.getLanguage(lang)) {
          try { return hljs.highlight(code, { language: lang }).value; } catch (e) {}
        }
        if (window.hljs) {
          try { return hljs.highlightAuto(code).value; } catch (e) {}
        }
        return code;
      }
    });
  }

  // =========================================================
  //  TOAST NOTIFICATION SYSTEM
  // =========================================================
  function showToast(message, type = 'info', duration = 4000) {
    const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
      <span class="toast-icon">${icons[type] || icons.info}</span>
      <span class="toast-text">${message}</span>
      <button class="toast-dismiss" onclick="this.closest('.toast').remove()">×</button>
    `;
    toastContainer.appendChild(toast);

    // Play subtle sound
    if (localStorage.getItem('RAG_SOUND_ENABLED') !== 'false') {
      playTone(type === 'error' ? 300 : type === 'success' ? 800 : 600, 80);
    }

    setTimeout(() => {
      toast.classList.add('removing');
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  // Web Audio API tone
  function playTone(freq, duration) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = freq;
      osc.type = 'sine';
      gain.gain.value = 0.03;
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration / 1000);
      osc.start();
      osc.stop(ctx.currentTime + duration / 1000);
    } catch (e) { /* ignore audio errors */ }
  }

  // =========================================================
  //  THEME TOGGLE (Light/Dark)
  // =========================================================
  const savedTheme = localStorage.getItem('RAG_THEME') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  updateThemeIcons(savedTheme);

  themeToggleBtn.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('RAG_THEME', next);
    updateThemeIcons(next);
    showToast(`Switched to ${next} theme`, 'info', 2000);
  });

  function updateThemeIcons(theme) {
    const darkIcon = document.querySelector('.theme-icon-dark');
    const lightIcon = document.querySelector('.theme-icon-light');
    if (theme === 'dark') {
      darkIcon?.classList.remove('hidden');
      lightIcon?.classList.add('hidden');
    } else {
      darkIcon?.classList.add('hidden');
      lightIcon?.classList.remove('hidden');
    }
  }

  // =========================================================
  //  SOUND TOGGLE
  // =========================================================
  const soundEnabled = localStorage.getItem('RAG_SOUND_ENABLED') !== 'false';
  updateSoundIcons(soundEnabled);

  soundToggleBtn?.addEventListener('click', () => {
    const isOn = localStorage.getItem('RAG_SOUND_ENABLED') !== 'false';
    const next = !isOn;
    localStorage.setItem('RAG_SOUND_ENABLED', String(next));
    updateSoundIcons(next);
    showToast(next ? 'Sound effects enabled' : 'Sound effects muted', 'info', 2000);
  });

  function updateSoundIcons(on) {
    const iconOn = soundToggleBtn?.querySelector('.sound-icon-on');
    const iconOff = soundToggleBtn?.querySelector('.sound-icon-off');
    if (on) {
      iconOn?.classList.remove('hidden');
      iconOff?.classList.add('hidden');
      soundToggleBtn?.classList.remove('sound-off');
    } else {
      iconOn?.classList.add('hidden');
      iconOff?.classList.remove('hidden');
      soundToggleBtn?.classList.add('sound-off');
    }
  }

  // =========================================================
  //  CHAT HISTORY / SESSION MANAGEMENT
  // =========================================================
  let activeSessionId = 'default';
  let chatSessions = loadChatSessions();
  renderSessionList();

  chatHistoryToggle?.addEventListener('click', () => {
    chatHistoryPanel?.classList.toggle('open');
  });

  newSessionBtn?.addEventListener('click', () => {
    createNewSession();
  });

  function loadChatSessions() {
    try {
      const raw = localStorage.getItem('RAG_CHAT_SESSIONS');
      return raw ? JSON.parse(raw) : [{ id: 'default', name: 'Current Session', time: Date.now(), messages: [] }];
    } catch (e) {
      return [{ id: 'default', name: 'Current Session', time: Date.now(), messages: [] }];
    }
  }

  function saveChatSessions() {
    try {
      localStorage.setItem('RAG_CHAT_SESSIONS', JSON.stringify(chatSessions));
    } catch (e) {
      console.warn('Failed to save chat sessions:', e);
    }
  }

  function saveCurrentMessages() {
    const session = chatSessions.find(s => s.id === activeSessionId);
    if (!session) return;
    // Serialize chat messages from DOM
    const msgs = [];
    chatMessages.querySelectorAll('.message').forEach(msgEl => {
      const isUser = msgEl.classList.contains('user');
      const contentEl = msgEl.querySelector('.msg-content') || msgEl.querySelector('.bubble');
      const text = contentEl ? contentEl.textContent.trim() : '';
      if (text && !msgEl.querySelector('.typing-indicator') && !msgEl.querySelector('.circular-progress-container')) {
        msgs.push({ role: isUser ? 'user' : 'assistant', text });
      }
    });
    session.messages = msgs.slice(-50); // Keep last 50 messages
    session.time = Date.now();
    // Auto-name from first user message
    if (session.name === 'New Session' || session.name === 'Current Session') {
      const firstUser = msgs.find(m => m.role === 'user');
      if (firstUser) {
        session.name = firstUser.text.substring(0, 40) + (firstUser.text.length > 40 ? '...' : '');
      }
    }
    saveChatSessions();
    renderSessionList();
  }

  function createNewSession() {
    saveCurrentMessages();
    const id = 'session_' + Date.now();
    const session = { id, name: 'New Session', time: Date.now(), messages: [] };
    chatSessions.unshift(session);
    activeSessionId = id;
    chatMessages.innerHTML = `
      <div class="message assistant msg-animate">
        <div class="avatar">🤖</div>
        <div class="bubble">New session started! Ask a question about your uploaded documents.</div>
      </div>
    `;
    saveChatSessions();
    renderSessionList();
    showToast('New chat session created', 'info', 2000);
  }

  function switchSession(sessionId) {
    if (sessionId === activeSessionId) return;
    saveCurrentMessages();
    activeSessionId = sessionId;
    const session = chatSessions.find(s => s.id === sessionId);
    chatMessages.innerHTML = '';
    if (session && session.messages.length > 0) {
      session.messages.forEach(msg => {
        addMessage(msg.role, msg.text);
      });
    } else {
      chatMessages.innerHTML = `
        <div class="message assistant msg-animate">
          <div class="avatar">🤖</div>
          <div class="bubble">Welcome! Upload your <strong>PDF documents</strong> in the sidebar. Answers appear with page-level citations.</div>
        </div>
      `;
    }
    renderSessionList();
    showToast(`Switched to: ${session?.name || 'Session'}`, 'info', 2000);
  }

  function deleteSession(sessionId) {
    if (sessionId === 'default') return;
    chatSessions = chatSessions.filter(s => s.id !== sessionId);
    if (sessionId === activeSessionId) {
      activeSessionId = chatSessions[0]?.id || 'default';
      switchSession(activeSessionId);
    }
    saveChatSessions();
    renderSessionList();
    showToast('Session deleted', 'info', 2000);
  }

  function renderSessionList() {
    if (!sessionListEl) return;
    sessionListEl.innerHTML = '';
    chatSessions.forEach(session => {
      const item = document.createElement('div');
      item.className = `session-item${session.id === activeSessionId ? ' active' : ''}`;
      item.dataset.session = session.id;

      const timeStr = new Date(session.time).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

      item.innerHTML = `
        <span class="session-item-label">${escapeHtml(session.name)}</span>
        <span class="session-item-time">${timeStr}</span>
        ${session.id !== 'default' ? '<button class="session-delete-btn" title="Delete session">✕</button>' : ''}
      `;

      item.addEventListener('click', (e) => {
        if (e.target.closest('.session-delete-btn')) {
          e.stopPropagation();
          deleteSession(session.id);
          return;
        }
        switchSession(session.id);
      });

      sessionListEl.appendChild(item);
    });
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // =========================================================
  //  SIDEBAR COLLAPSE / TOGGLE
  // =========================================================
  const savedSidebar = localStorage.getItem('RAG_SIDEBAR_COLLAPSED');
  if (savedSidebar === 'true') sidebar.classList.add('collapsed');

  sidebarCollapseBtn.addEventListener('click', () => {
    sidebar.classList.add('collapsed');
    localStorage.setItem('RAG_SIDEBAR_COLLAPSED', 'true');
  });

  sidebarToggleBtn.addEventListener('click', () => {
    if (window.innerWidth <= 768) {
      sidebar.classList.toggle('open');
      sidebarOverlay.classList.toggle('hidden', !sidebar.classList.contains('open'));
      sidebarOverlay.classList.toggle('visible', sidebar.classList.contains('open'));
    } else {
      sidebar.classList.toggle('collapsed');
      localStorage.setItem('RAG_SIDEBAR_COLLAPSED', sidebar.classList.contains('collapsed'));
    }
  });

  sidebarOverlay.addEventListener('click', () => {
    sidebar.classList.remove('open');
    sidebarOverlay.classList.add('hidden');
    sidebarOverlay.classList.remove('visible');
  });

  // =========================================================
  //  SCROLL-TO-BOTTOM BUTTON
  // =========================================================
  chatMessages.addEventListener('scroll', () => {
    const distFromBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight;
    scrollToBottomBtn.classList.toggle('hidden', distFromBottom < 100);
  });

  scrollToBottomBtn.addEventListener('click', () => {
    chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: 'smooth' });
  });

  // =========================================================
  //  GOOGLE AUTH & SESSION
  // =========================================================
  let currentUser = null;
  loadSavedUserSession();
  initGoogleAuth();

  function loadSavedUserSession() {
    try {
      const savedUserStr = localStorage.getItem('RAG_USER_SESSION');
      if (savedUserStr) {
        currentUser = JSON.parse(savedUserStr);
        renderUserSession(currentUser);
      } else if (localStorage.getItem('RAG_INTRO_DISMISSED') !== 'true') {
        identityGate?.classList.remove('hidden');
      }
    } catch (e) { console.error('Failed to load user session:', e); }
  }

  function saveUserSession(user) {
    currentUser = user;
    localStorage.setItem('RAG_USER_SESSION', JSON.stringify(user));
    renderUserSession(user);
  }

  function clearUserSession() {
    currentUser = null;
    localStorage.removeItem('RAG_USER_SESSION');
    authLoggedIn.classList.add('hidden');
    authLoggedOut.classList.remove('hidden');
  }

  function renderUserSession(user) {
    if (!user) return;
    authLoggedOut.classList.add('hidden');
    authLoggedIn.classList.remove('hidden');
    userDisplayName.textContent = user.name || 'Student User';
    userDisplayEmail.textContent = user.email || 'student@college.edu';
    identityGate?.classList.add('hidden');
    if (user.picture) {
      userAvatarImg.src = user.picture;
      userAvatarImg.classList.remove('hidden');
      userAvatarFallback.classList.add('hidden');
    } else {
      userAvatarFallback.textContent = (user.name || 'S').charAt(0).toUpperCase();
      userAvatarImg.classList.add('hidden');
      userAvatarFallback.classList.remove('hidden');
    }
  }

  async function initGoogleAuth() {
    let clientId = "";
    try {
      const res = await fetch('/api/config');
      if (res.ok) { const config = await res.json(); clientId = config.google_client_id; }
    } catch (e) { console.warn('Could not fetch backend auth config:', e); }

    demoLoginBtn.addEventListener('click', () => {
      if (clientId && window.google && window.google.accounts) {
        window.google.accounts.id.prompt();
      } else {
        const mockUser = {
          user_id: 'google_user_demo_101',
          name: 'Santhosh (Student)',
          email: 'santhosh.student@college.edu',
          picture: null
        };
        saveUserSession(mockUser);
        addMessage('assistant', `👋 Welcome back, **${mockUser.name}**! You are signed in.`);
        showToast(`Signed in as ${mockUser.name}`, 'success');
      }
    });

    identitySigninBtn?.addEventListener('click', () => demoLoginBtn.click());
    identityGuestBtn?.addEventListener('click', () => {
      localStorage.setItem('RAG_INTRO_DISMISSED', 'true');
      identityGate?.classList.add('hidden');
      showToast('Workspace unlocked — sign in whenever you are ready.', 'info', 3200);
    });

    signoutBtn.addEventListener('click', () => {
      clearUserSession();
      addMessage('assistant', '👋 You have signed out.');
      showToast('Signed out successfully', 'info');
    });

    if (clientId && window.google && window.google.accounts) {
      try {
        window.google.accounts.id.initialize({ client_id: clientId, callback: handleGoogleCredentialResponse });
        window.google.accounts.id.renderButton(
          document.getElementById('google-signin-btn-container'),
          { theme: 'outline', size: 'large', width: '100%' }
        );
      } catch (err) { console.error('Google Auth Init error:', err); }
    }
  }

  async function handleGoogleCredentialResponse(response) {
    if (!response || !response.credential) return;
    try {
      const res = await fetch('/api/auth/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: response.credential })
      });
      if (res.ok) {
        const authData = await res.json();
        if (authData.authenticated && authData.user) {
          saveUserSession(authData.user);
          addMessage('assistant', `✅ Signed in as **${authData.user.name}** (${authData.user.email})`);
          showToast(`Signed in as ${authData.user.name}`, 'success');
        }
      }
    } catch (e) { console.error('Auth verification error:', e); }
  }

  // =========================================================
  //  STATUS POLLING
  // =========================================================
  // Show skeleton while first status loads
  showFileListSkeleton();
  checkStatus();

  function showFileListSkeleton() {
    fileList.innerHTML = `
      <div class="file-list-skeleton">
        <div class="file-skeleton-item"><div class="file-skeleton-icon skeleton"></div><div class="file-skeleton-content"><div class="file-skeleton-name skeleton"></div><div class="file-skeleton-meta skeleton"></div></div></div>
        <div class="file-skeleton-item"><div class="file-skeleton-icon skeleton"></div><div class="file-skeleton-content"><div class="file-skeleton-name skeleton" style="width:55%"></div><div class="file-skeleton-meta skeleton" style="width:35%"></div></div></div>
      </div>
    `;
  }

  async function checkStatus() {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        statusBadge.className = 'status-val';
        if (data.is_ready) {
          statusBadge.textContent = data.is_processing ? 'Indexing...' : 'Ready';
          statusBadge.classList.add(data.is_processing ? 'status-processing' : 'status-ready');
        } else {
          statusBadge.textContent = 'Not Ready';
          statusBadge.classList.add('status-not-ready');
        }
        chunksCount.textContent = data.total_chunks;

        // Extra stats
        avgChunkSize.textContent = data.avg_chunk_size > 0 ? `${Math.round(data.avg_chunk_size)} chars` : '—';
        indexTime.textContent = data.total_indexing_time > 0 ? `${data.total_indexing_time}s` : '—';

        renderFileList(data.filenames, data.file_details || []);
      }
    } catch (err) { console.error('Error fetching status:', err); }
  }

  function renderFileList(filenames, fileDetails) {
    fileList.innerHTML = '';
    if (!filenames || !filenames.length) {
      fileList.innerHTML = '<div class="file-item" style="color: var(--text-muted);">No documents uploaded</div>';
      fileSearchWrapper.style.display = 'none';
      return;
    }

    fileSearchWrapper.style.display = filenames.length > 3 ? 'block' : 'none';

    const detailsMap = {};
    (fileDetails || []).forEach(d => detailsMap[d.filename] = d);

    filenames.forEach(fn => {
      const detail = detailsMap[fn] || {};
      const item = document.createElement('div');
      item.className = 'file-item';
      item.dataset.filename = fn;

      const sizeKB = detail.size_bytes ? (detail.size_bytes / 1024).toFixed(1) + ' KB' : '';
      const pages = detail.page_count ? detail.page_count + 'p' : '';
      const chunks = detail.chunk_count ? detail.chunk_count + ' chunks' : '';
      const metaParts = [sizeKB, pages, chunks].filter(Boolean).join(' · ');

      item.innerHTML = `
        <span style="font-size:1.2rem;">📄</span>
        <div class="file-item-info">
          <div class="file-item-name" title="${fn}">${fn}</div>
          ${metaParts ? `<div class="file-item-meta">${metaParts}</div>` : ''}
        </div>
        <div class="file-item-actions">
          <button class="file-action-btn summarize" title="Summarize" data-file="${fn}">📝</button>
          <button class="file-action-btn delete" title="Remove" data-file="${fn}">✕</button>
        </div>
      `;
      fileList.appendChild(item);
    });

    // Attach file action handlers
    fileList.querySelectorAll('.file-action-btn.delete').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeFile(btn.dataset.file);
      });
    });

    fileList.querySelectorAll('.file-action-btn.summarize').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        summarizeFile(btn.dataset.file);
      });
    });
  }

  // File search/filter
  fileSearchInput.addEventListener('input', () => {
    const query = fileSearchInput.value.toLowerCase();
    fileList.querySelectorAll('.file-item').forEach(item => {
      const fn = item.dataset.filename || '';
      item.style.display = fn.toLowerCase().includes(query) ? '' : 'none';
    });
  });

  // =========================================================
  //  FILE UPLOAD & DRAG-DROP
  // =========================================================
  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) handleFilesUpload(e.dataTransfer.files);
  });
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length) handleFilesUpload(e.target.files);
  });

  // Global drag-drop on body
  document.body.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (e.dataTransfer.types.includes('Files')) dropzone.classList.add('dragover');
  });
  document.body.addEventListener('dragleave', (e) => {
    if (e.relatedTarget === null) dropzone.classList.remove('dragover');
  });
  document.body.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) handleFilesUpload(e.dataTransfer.files);
  });

  async function handleFilesUpload(files) {
    const pdfFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (!pdfFiles.length) {
      showToast('Please upload PDF files only.', 'warning');
      return;
    }

    const formData = new FormData();
    pdfFiles.forEach(f => formData.append('files', f));

    showToast(`Uploading ${pdfFiles.length} PDF(s)...`, 'info', 2000);
    const progressMsgId = addCircularProgressMessage(pdfFiles.length);

    try {
      const res = await fetch('/api/upload', { method: 'POST', body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Upload failed');
      }
      const data = await res.json();
      pollProgress(data.task_id, progressMsgId);
    } catch (err) {
      removeElement(progressMsgId);
      addMessage('assistant', `❌ Error uploading: ${err.message}`);
      showToast(`Upload failed: ${err.message}`, 'error');
    }
  }

  // =========================================================
  //  CIRCULAR PROGRESS INDICATOR
  // =========================================================
  function addCircularProgressMessage(fileCount) {
    const id = 'progress-' + Date.now();
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant msg-animate';
    msgDiv.id = id;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = '🤖';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = `
      <div class="circular-progress-container" id="${id}-container">
        <div class="circular-progress-wrapper">
          <svg class="circular-progress-svg" viewBox="0 0 90 90">
            <defs>
              <linearGradient id="progressGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#6366f1"/>
                <stop offset="50%" stop-color="#8b5cf6"/>
                <stop offset="100%" stop-color="#3b82f6"/>
              </linearGradient>
            </defs>
            <circle class="circular-progress-bg" cx="45" cy="45" r="42"/>
            <circle class="circular-progress-fill" id="${id}-circle" cx="45" cy="45" r="42"/>
          </svg>
          <div class="circular-progress-text">
            <span class="circular-progress-percent" id="${id}-percent">0%</span>
            <span class="circular-progress-label">Indexing</span>
          </div>
        </div>
        <div class="progress-info">
          <div class="progress-stage" id="${id}-stage">Processing ${fileCount} PDF(s)...</div>
          <div class="progress-details" id="${id}-details">Pages: 0 | Chunks: 0</div>
          <div class="progress-time" id="${id}-time">0.0s</div>
        </div>
        <div class="chat-now-badge hidden" id="${id}-chatnow">💬 You can start asking questions now!</div>
      </div>
    `;

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
  }

  function updateCircularProgress(id, data) {
    const circle = document.getElementById(`${id}-circle`);
    const percentEl = document.getElementById(`${id}-percent`);
    const stage = document.getElementById(`${id}-stage`);
    const details = document.getElementById(`${id}-details`);
    const timeEl = document.getElementById(`${id}-time`);
    const chatNow = document.getElementById(`${id}-chatnow`);

    const pct = Math.round(data.progress * 100);
    const circumference = 2 * Math.PI * 42; // ~264

    if (circle) {
      circle.style.strokeDasharray = circumference;
      circle.style.strokeDashoffset = circumference - (circumference * data.progress);
    }
    if (percentEl) percentEl.textContent = `${pct}%`;
    if (stage) stage.textContent = data.stage_label;
    if (details) details.textContent = `Pages: ${data.pages_extracted} | Chunks: ${data.chunks_created}`;
    if (timeEl) timeEl.textContent = `${data.elapsed_seconds}s`;

    if (data.status === 'background' && chatNow) {
      chatNow.classList.remove('hidden');
    }
  }

  function finalizeCircularProgress(id, data) {
    const container = document.getElementById(`${id}-container`);
    if (!container) return;

    const isError = data.status === 'error';
    container.classList.add(isError ? 'error' : 'complete');

    const circle = document.getElementById(`${id}-circle`);
    if (circle) {
      const circumference = 2 * Math.PI * 42;
      circle.style.strokeDashoffset = 0;
      circle.style.stroke = isError ? 'var(--accent-red)' : 'var(--accent-green)';
    }

    const percentEl = document.getElementById(`${id}-percent`);
    if (percentEl) percentEl.textContent = isError ? '✕' : '✓';

    const stage = document.getElementById(`${id}-stage`);
    if (stage) stage.textContent = isError ? 'Processing Failed' : data.stage_label;

    const chatNow = document.getElementById(`${id}-chatnow`);
    if (chatNow) chatNow.classList.add('hidden');

    if (!isError) {
      showToast(`Indexed ${data.pages_extracted} pages → ${data.chunks_created} chunks in ${data.elapsed_seconds}s`, 'success');
    } else {
      showToast(`Indexing failed: ${data.error || 'Unknown error'}`, 'error');
    }
  }

  function removeElement(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  async function pollProgress(taskId, progressMsgId) {
    const poll = async () => {
      try {
        const res = await fetch(`/api/progress/${taskId}`);
        if (!res.ok) throw new Error('Task not found');
        const data = await res.json();
        updateCircularProgress(progressMsgId, data);

        if (data.status === 'complete' || data.status === 'error') {
          finalizeCircularProgress(progressMsgId, data);
          checkStatus();
          return;
        }
        setTimeout(poll, 400);
      } catch (err) { setTimeout(poll, 800); }
    };
    poll();
  }

  // =========================================================
  //  PER-FILE ACTIONS (Remove, Summarize)
  // =========================================================
  async function removeFile(filename) {
    if (!confirm(`Remove "${filename}" from the index?`)) return;
    try {
      const res = await fetch(`/api/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      if (res.ok) {
        showToast(`Removed "${filename}"`, 'success');
        checkStatus();
      } else {
        const err = await res.json();
        showToast(err.detail || 'Failed to remove file', 'error');
      }
    } catch (e) {
      showToast('Failed to remove file', 'error');
    }
  }

  async function summarizeFile(filename) {
    showToast(`Generating summary for "${filename}"...`, 'info', 3000);
    try {
      const res = await fetch(`/api/summarize/${encodeURIComponent(filename)}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        addMessage('assistant', `📝 **Summary of ${filename}:**\n\n${data.summary}`);
        showToast('Summary generated!', 'success');
      } else {
        showToast('Failed to generate summary', 'error');
      }
    } catch (e) {
      showToast('Failed to generate summary', 'error');
    }
  }

  // =========================================================
  //  INLINE ATTACHMENTS (Images, small PDFs)
  // =========================================================
  let inlineAttachments = [];
  const inlineFileInput = document.getElementById('inline-file-input');
  const inlineAttachBtn = document.getElementById('inline-attach-btn');
  const inlineAttachmentPreview = document.getElementById('inline-attachment-preview');
  
  if (inlineAttachBtn && inlineFileInput) {
    inlineAttachBtn.addEventListener('click', () => inlineFileInput.click());
    inlineFileInput.addEventListener('change', (e) => {
      handleInlineFiles(e.target.files);
      inlineFileInput.value = '';
    });
  }

  // Handle Drag & Drop on chat input
  chatInput.addEventListener('dragover', (e) => {
    e.preventDefault();
    chatInput.style.borderColor = 'var(--accent-primary)';
  });
  chatInput.addEventListener('dragleave', () => {
    chatInput.style.borderColor = 'var(--glass-border)';
  });
  chatInput.addEventListener('drop', (e) => {
    e.preventDefault();
    chatInput.style.borderColor = 'var(--glass-border)';
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleInlineFiles(e.dataTransfer.files);
    }
  });

  // Handle Paste
  chatInput.addEventListener('paste', (e) => {
    if (e.clipboardData.files && e.clipboardData.files.length > 0) {
      handleInlineFiles(e.clipboardData.files);
    }
  });

  async function handleInlineFiles(files) {
    for (const file of files) {
      if (inlineAttachments.length >= 5) {
        showToast('Maximum 5 attachments allowed per message.', 'warning');
        break;
      }
      if (file.size > 10 * 1024 * 1024) {
        showToast(`"${file.name}" is too large (>10MB). Use Document Upload.`, 'error');
        continue;
      }
      const validExtensions = ['.heic', '.heif', '.svg', '.avif', '.ico', '.bmp', '.tiff', '.tif', '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif'];
      const fileExt = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
      
      if (!file.type.startsWith('image/') && !validExtensions.includes(fileExt)) {
        showToast(`"${file.name}" type not supported inline.`, 'error');
        continue;
      }

      try {
        const base64Data = await readFileAsBase64(file);
        // Strip the data URL prefix
        const base64 = base64Data.split(',')[1];
        
        let previewUrl = null;
        // Don't try to preview formats browsers can't natively render well
        const unrenderable = ['.heic', '.heif', '.tiff', '.tif'];
        if ((file.type.startsWith('image/') || validExtensions.includes(fileExt)) && !unrenderable.includes(fileExt) && fileExt !== '.pdf') {
            previewUrl = base64Data;
        }
        
        inlineAttachments.push({
          file: file,
          filename: file.name,
          mime_type: file.type,
          data: base64,
          previewUrl: previewUrl
        });
      } catch (err) {
        showToast(`Failed to read "${file.name}"`, 'error');
      }
    }
    renderInlineAttachments();
  }

  function renderInlineAttachments() {
    if (!inlineAttachmentPreview) return;
    inlineAttachmentPreview.innerHTML = '';
    inlineAttachments.forEach((att, index) => {
      const chip = document.createElement('div');
      chip.className = 'attachment-chip';
      
      let visual = '';
      if (att.previewUrl) {
        visual = `<img src="${att.previewUrl}" class="thumbnail" alt="preview">`;
      } else {
        visual = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`;
      }

      chip.innerHTML = `
        ${visual}
        <span class="filename" title="${att.filename}">${att.filename.length > 15 ? att.filename.substring(0, 15) + '...' : att.filename}</span>
        <button class="remove-att-btn" data-index="${index}" title="Remove attachment">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      `;
      inlineAttachmentPreview.appendChild(chip);
    });

    // Add remove listeners
    inlineAttachmentPreview.querySelectorAll('.remove-att-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const idx = parseInt(e.currentTarget.getAttribute('data-index'), 10);
        inlineAttachments.splice(idx, 1);
        renderInlineAttachments();
      });
    });
  }

  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  // =========================================================
  //  CHAT MESSAGING — STREAMING SSE
  // =========================================================
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  sendBtn.addEventListener('click', sendMessage);

  async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question && inlineAttachments.length === 0) return;

    let displayMsg = question;
    if (inlineAttachments.length > 0) {
        displayMsg += `\n\n*Attached ${inlineAttachments.length} file(s)*`;
    }

    addMessage('user', displayMsg);
    chatInput.value = '';
    chatInput.style.height = '56px';

    const attachmentsPayload = inlineAttachments.map(att => ({
        filename: att.filename,
        mime_type: att.mime_type,
        data: att.data
    }));

    // Clear attachments UI
    inlineAttachments = [];
    renderInlineAttachments();

    const eli5Mode = eli5Toggle.checked;
    const hasImage = attachmentsPayload.some(a => a.mime_type.startsWith('image/'));

    // Create the assistant message bubble immediately with the typing indicator inside it
    const { msgDiv, bubble, contentDiv } = createStreamingMessage();
    const typingIndicator = document.createElement('div');
    
    let textCycleInterval = null;

    if (hasImage) {
      typingIndicator.className = 'image-processing-indicator fade-in';
      typingIndicator.innerHTML = `
        <div class="image-processing-thumbnail"></div>
        <div class="image-processing-text" aria-live="polite" style="transition: opacity 0.3s ease-in-out;">Looking closely...</div>
      `;
      contentDiv.appendChild(typingIndicator);
      
      const phrases = ["Looking closely...", "Reading the details...", "Almost there..."];
      let phraseIdx = 0;
      const textEl = typingIndicator.querySelector('.image-processing-text');
      textCycleInterval = setInterval(() => {
        phraseIdx = (phraseIdx + 1) % phrases.length;
        textEl.style.opacity = 0;
        setTimeout(() => {
          textEl.textContent = phrases[phraseIdx];
          textEl.style.opacity = 1;
        }, 300);
      }, 1800);
    } else {
      typingIndicator.className = 'typing-indicator claude-thinking-indicator';
      typingIndicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
      contentDiv.appendChild(typingIndicator);
    }

    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          question, 
          eli5_mode: eli5Mode,
          attachments: attachmentsPayload
        })
      });

      if (!res.ok) {
        if (textCycleInterval) clearInterval(textCycleInterval);
        typingIndicator.remove();
        const err = await res.json();
        throw new Error(err.detail || 'Request failed');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let fullText = '';
      let buffer = '';
      let metadata = null;
      let isFirstToken = true;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));

            if (data.status === 'searching') {
              typingIndicator.innerHTML = `<span>${data.message}</span>`;
              typingIndicator.classList.add('searching-status');
              continue;
            }

            if (data.done) {
              metadata = data;
            } else if (data.token) {
              if (isFirstToken) {
                // Immediately swap out the typing indicator when the first token arrives
                if (textCycleInterval) clearInterval(textCycleInterval);
                typingIndicator.classList.add('fade-out');
                setTimeout(() => typingIndicator.remove(), 300);
                contentDiv.classList.add('fade-in');
                isFirstToken = false;
              }
              fullText += data.token;
              // Throttled markdown render
              renderMarkdownContent(contentDiv, fullText);
              chatMessages.scrollTop = chatMessages.scrollHeight;
            }
          } catch (parseErr) { /* skip bad JSON */ }
        }
      }

      if (isFirstToken) {
        typingIndicator.remove();
      }

      // Final render with full markdown
      renderMarkdownContent(contentDiv, fullText);
      addCodeCopyButtons(bubble);

      // Add action bar, confidence badge, sources, follow-ups
      if (metadata) {
        appendMessageMeta(bubble, contentDiv, fullText, question, metadata);
      }

      chatMessages.scrollTop = chatMessages.scrollHeight;

      // Save messages to session history
      saveCurrentMessages();

      if (localStorage.getItem('RAG_SOUND_ENABLED') !== 'false') {
        playTone(800, 100);
      }

    } catch (err) {
      removeElement(typingId);
      addMessage('assistant', `❌ Error: ${err.message}`);
      showToast(`Chat error: ${err.message}`, 'error');
    }
  }

  function createStreamingMessage() {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant msg-animate';

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = '🤖';

    const bubble = document.createElement('div');
    bubble.className = 'bubble markdown-body';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'msg-content';
    bubble.appendChild(contentDiv);

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    return { msgDiv, bubble, contentDiv };
  }

  function renderMarkdownContent(el, text) {
    if (window.marked && typeof window.marked.parse === 'function') {
      el.innerHTML = marked.parse(text);
    } else {
      el.innerHTML = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    }
  }

  function appendMessageMeta(bubble, contentDiv, fullText, question, metadata) {
    const isNonAnswer = metadata.is_non_answer === true;

    // --- Only show confidence, source tag, citations, and follow-ups for REAL answers ---
    if (!isNonAnswer) {

      // Confidence badge
      if (metadata.confidence_score !== undefined && metadata.confidence_score > 0) {
        const score = metadata.confidence_score;
        const level = score >= 0.7 ? 'high' : score >= 0.4 ? 'medium' : 'low';
        const label = score >= 0.7 ? 'High confidence' : score >= 0.4 ? 'Medium confidence' : 'Low confidence';
        const badge = document.createElement('div');
        badge.className = `confidence-badge ${level}`;
        badge.innerHTML = `<span>${(score * 100).toFixed(0)}%</span> ${label}`;
        contentDiv.appendChild(badge);
      }

      // Source Type Label (differentiated by confidence)
      if (metadata.source_type) {
        const typeLabel = document.createElement('div');
        if (metadata.source_type === 'web') {
          typeLabel.className = 'source-label source-label-web';
          typeLabel.innerHTML = '🌐 From the web (not found in your documents)';
        } else if (metadata.confidence_score >= 0.75) {
          typeLabel.className = 'source-label source-label-docs';
          typeLabel.innerHTML = '📄 From your documents';
        } else {
          typeLabel.className = 'source-label source-label-weak';
          typeLabel.innerHTML = '⚠️ Weak match in your documents';
        }
        contentDiv.appendChild(typeLabel);
      }

      // Sources (with keyword highlighting)
      if (metadata.sources && metadata.sources.length > 0) {
        const sourcesContainer = document.createElement('div');
        sourcesContainer.className = 'sources-container';

        const toggleBtn = document.createElement('div');
        toggleBtn.className = 'sources-toggle';
        toggleBtn.innerHTML = `📚 View ${metadata.sources.length} Source Citation(s) ▼`;

        const sourcesList = document.createElement('div');
        sourcesList.className = 'sources-list';

        const queryKeywords = question.toLowerCase().split(/\s+/).filter(w => w.length > 3);

        metadata.sources.forEach(s => {
          const card = document.createElement('div');
          card.className = 'source-card';
          const highlightedSnippet = highlightKeywords(s.snippet, queryKeywords);
          
          let headerContent = '';
          if (metadata.source_type === 'web') {
            headerContent = `<span>🌐 <a href="${s.metadata.url}" target="_blank" style="color: inherit; text-decoration: underline;">${escapeHtml(s.metadata.title)}</a></span>`;
          } else {
            headerContent = `<span>📄 ${escapeHtml(s.filename)}</span><span>Page ${s.page_number}</span>`;
          }
          
          card.innerHTML = `
            <div class="source-header">
              ${headerContent}
            </div>
            <div class="source-snippet">${highlightedSnippet}</div>
          `;
          sourcesList.appendChild(card);
        });

        toggleBtn.addEventListener('click', () => {
          const isOpen = sourcesList.classList.toggle('open');
          toggleBtn.innerHTML = `📚 View ${metadata.sources.length} Source Citation(s) ${isOpen ? '▲' : '▼'}`;
        });

        sourcesContainer.appendChild(toggleBtn);
        sourcesContainer.appendChild(sourcesList);
        bubble.appendChild(sourcesContainer);
      }

      // Follow-up suggestion chips
      if (metadata.follow_up_suggestions && metadata.follow_up_suggestions.length > 0) {
        const chipsDiv = document.createElement('div');
        chipsDiv.className = 'follow-up-chips';

        metadata.follow_up_suggestions.forEach(suggestion => {
          const chip = document.createElement('button');
          chip.className = 'follow-up-chip';
          chip.textContent = suggestion;
          chip.addEventListener('click', () => {
            chatInput.value = suggestion;
            sendMessage();
          });
          chipsDiv.appendChild(chip);
        });

        bubble.appendChild(chipsDiv);
      }

    } else {
      // Non-answer: show a neutral "no answer found" label only
      const noAnswerLabel = document.createElement('div');
      noAnswerLabel.className = 'source-label source-label-none';
      noAnswerLabel.innerHTML = '❌ No answer found';
      contentDiv.appendChild(noAnswerLabel);
    }

    // Action bar (Copy, Regenerate) — always shown regardless of answer type
    const actionBar = document.createElement('div');
    actionBar.className = 'msg-action-bar';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-action-btn';
    copyBtn.innerHTML = '📋 Copy';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(fullText).then(() => {
        copyBtn.innerHTML = '✓ Copied!';
        copyBtn.classList.add('copied');
        setTimeout(() => {
          copyBtn.innerHTML = '📋 Copy';
          copyBtn.classList.remove('copied');
        }, 2000);
      });
    });

    const regenBtn = document.createElement('button');
    regenBtn.className = 'msg-action-btn';
    regenBtn.innerHTML = '🔄 Regenerate';
    regenBtn.addEventListener('click', () => {
      chatInput.value = question;
      sendMessage();
    });

    actionBar.appendChild(copyBtn);
    actionBar.appendChild(regenBtn);
    bubble.appendChild(actionBar);
  }

  // =========================================================
  //  CODE COPY BUTTONS
  // =========================================================
  function addCodeCopyButtons(container) {
    container.querySelectorAll('pre').forEach(pre => {
      if (pre.querySelector('.code-copy-btn')) return;
      pre.style.position = 'relative';
      const btn = document.createElement('button');
      btn.className = 'code-copy-btn';
      btn.innerHTML = '📋 Copy';
      btn.addEventListener('click', () => {
        const code = pre.querySelector('code');
        const text = code ? code.textContent : pre.textContent;
        navigator.clipboard.writeText(text).then(() => {
          btn.innerHTML = '✓ Copied!';
          btn.classList.add('copied');
          setTimeout(() => {
            btn.innerHTML = '📋 Copy';
            btn.classList.remove('copied');
          }, 2000);
        });
      });
      pre.appendChild(btn);
    });
  }

  // =========================================================
  //  KEYWORD HIGHLIGHTING FOR SOURCE SNIPPETS
  // =========================================================
  function highlightKeywords(text, keywords) {
    if (!keywords || !keywords.length) return escapeHtml(text);
    let escaped = escapeHtml(text);
    const uniqueKeywords = [...new Set(keywords)];
    uniqueKeywords.forEach(kw => {
      const safeKw = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`(${safeKw})`, 'gi');
      escaped = escaped.replace(regex, '<mark>$1</mark>');
    });
    return escaped;
  }

  // =========================================================
  //  GENERAL addMessage (non-streaming, for system messages)
  // =========================================================
  function addMessage(role, text, sources = []) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role} msg-animate`;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user'
      ? (currentUser && currentUser.name ? currentUser.name.charAt(0).toUpperCase() : '👤')
      : '🤖';

    const bubble = document.createElement('div');
    bubble.className = 'bubble markdown-body';

    renderMarkdownContent(bubble, text);

    if (sources && sources.length > 0) {
      const sourcesContainer = document.createElement('div');
      sourcesContainer.className = 'sources-container';
      const toggleBtn = document.createElement('div');
      toggleBtn.className = 'sources-toggle';
      toggleBtn.innerHTML = `📚 View ${sources.length} Source Citation(s) ▼`;
      const sourcesList = document.createElement('div');
      sourcesList.className = 'sources-list';
      sources.forEach(s => {
        const card = document.createElement('div');
        card.className = 'source-card';
        card.innerHTML = `
          <div class="source-header"><span>📄 ${s.filename}</span><span>Page ${s.page_number}</span></div>
          <div class="source-snippet">"${s.snippet}"</div>
        `;
        sourcesList.appendChild(card);
      });
      toggleBtn.addEventListener('click', () => {
        const isOpen = sourcesList.classList.toggle('open');
        toggleBtn.innerHTML = `📚 View ${sources.length} Source Citation(s) ${isOpen ? '▲' : '▼'}`;
      });
      sourcesContainer.appendChild(toggleBtn);
      sourcesContainer.appendChild(sourcesList);
      bubble.appendChild(sourcesContainer);
    }

    addCodeCopyButtons(bubble);
    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function addTypingIndicator() {
    const id = 'typing-' + Date.now();
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant msg-animate';
    msgDiv.id = id;
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = '🤖';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = `<div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
  }

  // =========================================================
  //  VOICE INPUT (Web Speech API)
  // =========================================================
  let recognition = null;
  let isRecording = false;

  if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (event) => {
      let transcript = '';
      for (let i = 0; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      chatInput.value = transcript;
    };

    recognition.onend = () => {
      isRecording = false;
      voiceInputBtn.classList.remove('recording');
    };

    recognition.onerror = (event) => {
      isRecording = false;
      voiceInputBtn.classList.remove('recording');
      if (event.error !== 'aborted') {
        showToast('Voice recognition error: ' + event.error, 'warning');
      }
    };
  }

  voiceInputBtn.addEventListener('click', () => {
    if (!recognition) {
      showToast('Speech recognition not supported in this browser', 'warning');
      return;
    }
    if (isRecording) {
      recognition.stop();
      isRecording = false;
      voiceInputBtn.classList.remove('recording');
    } else {
      recognition.start();
      isRecording = true;
      voiceInputBtn.classList.add('recording');
      showToast('Listening... speak now', 'info', 2000);
    }
  });

  // =========================================================
  //  EXPORT CHAT AS MARKDOWN
  // =========================================================
  exportChatBtn.addEventListener('click', () => {
    const messages = chatMessages.querySelectorAll('.message');
    let md = `# RAG Intelligence — Chat Export\n\nExported: ${new Date().toLocaleString()}\n\n---\n\n`;

    messages.forEach(msg => {
      const isUser = msg.classList.contains('user');
      const role = isUser ? '**You**' : '**AI Assistant**';
      const contentEl = msg.querySelector('.msg-content') || msg.querySelector('.bubble');
      const text = contentEl ? contentEl.textContent.trim() : '';
      if (text) {
        md += `### ${role}\n\n${text}\n\n---\n\n`;
      }
    });

    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rag-chat-export-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Chat exported as Markdown', 'success');
  });

  // =========================================================
  //  KEYBOARD SHORTCUTS
  // =========================================================
  document.addEventListener('keydown', (e) => {
    // Ctrl+K: Focus file search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      if (fileSearchWrapper.style.display !== 'none') {
        fileSearchInput.focus();
        if (sidebar.classList.contains('collapsed')) {
          sidebar.classList.remove('collapsed');
          localStorage.setItem('RAG_SIDEBAR_COLLAPSED', 'false');
        }
      } else {
        chatInput.focus();
      }
    }

    // Escape: Close mobile sidebar
    if (e.key === 'Escape') {
      if (sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
        sidebarOverlay.classList.add('hidden');
        sidebarOverlay.classList.remove('visible');
      }
    }
  });

  // Auto-resize textarea
  chatInput.addEventListener('input', () => {
    chatInput.style.height = '56px';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
  });

  // =========================================================
  //  CLEAR ACTION
  // =========================================================
  clearBtn.addEventListener('click', async () => {
    if (confirm('Clear the document index and chat history?')) {
      try {
        await fetch('/api/clear', { method: 'DELETE' });
        chatMessages.innerHTML = `
          <div class="message assistant msg-animate">
            <div class="avatar">🤖</div>
            <div class="bubble">Index cleared. Upload new PDF documents to start a fresh chat session.</div>
          </div>
        `;
        checkStatus();
        showToast('Index and chat cleared', 'info');
      } catch (err) {
        showToast('Failed to clear index', 'error');
      }
    }
  });

  // =========================================================
  //  AUTO-SAVE SESSIONS ON UNLOAD
  // =========================================================
  window.addEventListener('beforeunload', () => {
    saveCurrentMessages();
  });
});
