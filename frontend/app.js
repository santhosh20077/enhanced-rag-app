document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const apiKeyInput = document.getElementById('api-key-input');
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const statusBadge = document.getElementById('status-badge');
  const chunksCount = document.getElementById('chunks-count');
  const fileList = document.getElementById('file-list');
  const clearBtn = document.getElementById('clear-btn');
  const chatMessages = document.getElementById('chat-messages');
  const chatInput = document.getElementById('chat-input');
  const sendBtn = document.getElementById('send-btn');

  // Auth Elements
  const authLoggedOut = document.getElementById('auth-logged-out');
  const authLoggedIn = document.getElementById('auth-logged-in');
  const demoLoginBtn = document.getElementById('demo-login-btn');
  const signoutBtn = document.getElementById('signout-btn');
  const userAvatarImg = document.getElementById('user-avatar-img');
  const userAvatarFallback = document.getElementById('user-avatar-fallback');
  const userDisplayName = document.getElementById('user-display-name');
  const userDisplayEmail = document.getElementById('user-display-email');

  // ---------------------------------------------------------
  // 1. Google OAuth & Session Persistence
  // ---------------------------------------------------------
  let currentUser = null;

  // Load saved session on launch
  loadSavedUserSession();

  // Fetch backend config (e.g. google_client_id)
  initGoogleAuth();

  function loadSavedUserSession() {
    try {
      const savedUserStr = localStorage.getItem('RAG_USER_SESSION');
      if (savedUserStr) {
        currentUser = JSON.parse(savedUserStr);
        renderUserSession(currentUser);
      }
    } catch (e) {
      console.error('Failed to load user session:', e);
    }
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
      if (res.ok) {
        const config = await res.json();
        clientId = config.google_client_id;
      }
    } catch (e) {
      console.warn('Could not fetch backend auth config:', e);
    }

    // Handle demo button click
    demoLoginBtn.addEventListener('click', () => {
      if (clientId && window.google && window.google.accounts) {
        window.google.accounts.id.prompt();
      } else {
        // Instant Demo Login
        const mockUser = {
          user_id: 'google_user_demo_101',
          name: 'Santhosh (Student)',
          email: 'santhosh.student@college.edu',
          picture: null
        };
        saveUserSession(mockUser);
        addMessage('assistant', `👋 Welcome back, **${mockUser.name}**! You are signed in.`);
      }
    });

    signoutBtn.addEventListener('click', () => {
      clearUserSession();
      addMessage('assistant', '👋 You have signed out. Sign in anytime to resume your student workspace.');
    });

    // Initialize Google GIS if Client ID is configured
    if (clientId && window.google && window.google.accounts) {
      try {
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: handleGoogleCredentialResponse
        });
        window.google.accounts.id.renderButton(
          document.getElementById('google-signin-btn-container'),
          { theme: 'outline', size: 'large', width: '100%' }
        );
      } catch (err) {
        console.error('Google Auth Init error:', err);
      }
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
          addMessage('assistant', `✅ Successfully signed in as **${authData.user.name}** (${authData.user.email})`);
        }
      }
    } catch (e) {
      console.error('Auth verification error:', e);
    }
  }

  // ---------------------------------------------------------
  // 2. NVIDIA API Key Storage
  // ---------------------------------------------------------
  const savedKey = sessionStorage.getItem('NVIDIA_API_KEY');
  if (savedKey) {
    apiKeyInput.value = savedKey;
  }

  apiKeyInput.addEventListener('input', (e) => {
    sessionStorage.setItem('NVIDIA_API_KEY', e.target.value.trim());
  });

  checkStatus();

  // ---------------------------------------------------------
  // 3. File Upload Handlers
  // ---------------------------------------------------------
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

  async function handleFilesUpload(files) {
    const pdfFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (!pdfFiles.length) { alert('Please upload PDF files only.'); return; }

    const formData = new FormData();
    pdfFiles.forEach(f => formData.append('files', f));

    const progressMsgId = addProgressMessage(pdfFiles.length);

    try {
      const res = await fetch('/api/upload', { method: 'POST', body: formData });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Upload failed'); }
      const data = await res.json();
      pollProgress(data.task_id, progressMsgId);
    } catch (err) {
      removeElement(progressMsgId);
      addMessage('assistant', `❌ Error uploading: ${err.message}`);
    }
  }

  // ---------------------------------------------------------
  // 4. Progress Bar & Fast Progressive Indexing
  // ---------------------------------------------------------
  function addProgressMessage(fileCount) {
    const id = 'progress-' + Date.now();
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';
    msgDiv.id = id;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = '🤖';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = `
      <div class="progress-container" id="${id}-container">
        <div class="progress-header">
          <span class="progress-icon">⚡</span>
          <span class="progress-title">Processing ${fileCount} PDF(s)...</span>
          <span class="progress-time" id="${id}-time">0.0s</span>
        </div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill" id="${id}-bar" style="width: 0%"></div>
        </div>
        <div class="progress-stats">
          <span id="${id}-stage">Uploading...</span>
          <span id="${id}-percent">0%</span>
        </div>
        <div class="progress-details" id="${id}-details">Pages: 0 | Chunks: 0</div>
        <div class="chat-now-badge hidden" id="${id}-chatnow">💬 You can start asking questions now!</div>
      </div>
    `;

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
  }

  function updateProgressMessage(id, data) {
    const bar = document.getElementById(`${id}-bar`);
    const stage = document.getElementById(`${id}-stage`);
    const percent = document.getElementById(`${id}-percent`);
    const timeEl = document.getElementById(`${id}-time`);
    const details = document.getElementById(`${id}-details`);
    const chatNow = document.getElementById(`${id}-chatnow`);
    const container = document.getElementById(`${id}-container`);

    if (bar) bar.style.width = `${Math.round(data.progress * 100)}%`;
    if (stage) stage.textContent = data.stage_label;
    if (percent) percent.textContent = `${Math.round(data.progress * 100)}%`;
    if (timeEl) timeEl.textContent = `${data.elapsed_seconds}s`;
    if (details) details.textContent = `Pages: ${data.pages_extracted} | Chunks: ${data.chunks_created}`;

    if (data.status === 'background' && chatNow) {
      chatNow.classList.remove('hidden');
      if (container) container.classList.add('searchable');
    }
  }

  function finalizeProgressMessage(id, data) {
    const container = document.getElementById(id);
    if (!container) return;

    const bubble = container.querySelector('.bubble');
    if (!bubble) return;

    const isError = data.status === 'error';
    bubble.innerHTML = `
      <div class="progress-container ${isError ? 'error' : 'complete'}">
        <div class="progress-header">
          <span class="progress-icon">${isError ? '❌' : '✅'}</span>
          <span class="progress-title">${isError ? 'Processing Failed' : 'Ready!'}</span>
          <span class="progress-time">${data.elapsed_seconds}s</span>
        </div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill ${isError ? 'error' : 'complete'}" style="width: 100%"></div>
        </div>
        <div class="progress-stats">
          <span>${data.stage_label}</span>
        </div>
        ${!isError ? `<div class="progress-details complete-details">📄 ${data.pages_extracted} pages -> 🔗 ${data.chunks_created} chunks | Ask anything!</div>` : ''}
      </div>
    `;
  }

  function removeElement(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  async function pollProgress(taskId, progressMsgId) {
    const poll = async () => {
      try {
        const res = await fetch(`/api/progress/${taskId}`);
        if (!res.ok) return;
        const data = await res.json();
        updateProgressMessage(progressMsgId, data);

        if (data.status === 'complete' || data.status === 'error') {
          finalizeProgressMessage(progressMsgId, data);
          checkStatus();
          return;
        }
        setTimeout(poll, 400);
      } catch (err) {
        setTimeout(poll, 800);
      }
    };
    poll();
  }

  // ---------------------------------------------------------
  // 5. Index Status Polling
  // ---------------------------------------------------------
  async function checkStatus() {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        if (data.is_ready) {
          statusBadge.textContent = data.is_processing ? 'Indexing...' : 'Ready';
          statusBadge.style.color = data.is_processing ? '#f59e0b' : 'var(--accent-green)';
        } else {
          statusBadge.textContent = 'Not Ready';
          statusBadge.style.color = 'var(--accent-red)';
        }
        chunksCount.textContent = data.total_chunks;
        
        fileList.innerHTML = '';
        if (data.filenames && data.filenames.length) {
          data.filenames.forEach(fn => {
            const item = document.createElement('div');
            item.className = 'file-item';
            item.textContent = `📄 ${fn}`;
            fileList.appendChild(item);
          });
        } else {
          fileList.innerHTML = '<div class="file-item" style="color: var(--text-muted);">No documents uploaded</div>';
        }
      }
    } catch (err) {
      console.error('Error fetching status:', err);
    }
  }

  // ---------------------------------------------------------
  // 6. Chat Messaging
  // ---------------------------------------------------------
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  sendBtn.addEventListener('click', sendMessage);

  async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question) return;
    const apiKey = apiKeyInput.value.trim();

    addMessage('user', question);
    chatInput.value = '';
    const typingId = addTypingIndicator();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, api_key: apiKey || null })
      });
      removeElement(typingId);
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed'); }
      const data = await res.json();
      addMessage('assistant', data.answer, data.sources);
    } catch (err) {
      removeElement(typingId);
      addMessage('assistant', `❌ Error: ${err.message}`);
    }
  }

  function addMessage(role, text, sources = []) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? (currentUser && currentUser.name ? currentUser.name.charAt(0).toUpperCase() : '👤') : '🤖';

    const bubble = document.createElement('div');
    bubble.className = 'bubble markdown-body';
    if (window.marked && typeof window.marked.parse === 'function') {
      bubble.innerHTML = window.marked.parse(text);
    } else {
      let formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      bubble.innerHTML = formattedText;
    }

    if (sources && sources.length > 0) {
      const sourcesContainer = document.createElement('div');
      sourcesContainer.className = 'sources-container';

      const toggleBtn = document.createElement('div');
      toggleBtn.className = 'sources-toggle';
      toggleBtn.innerHTML = `📚 View ${sources.length} Source Citation(s) ▼`;

      const sourcesList = document.createElement('div');
      sourcesList.className = 'sources-list';

      sources.forEach((s) => {
        const card = document.createElement('div');
        card.className = 'source-card';
        card.innerHTML = `
          <div class="source-header">
            <span>📄 ${s.filename}</span>
            <span>Page ${s.page_number}</span>
          </div>
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

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function addTypingIndicator() {
    const id = 'typing-' + Date.now();
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';
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

  // ---------------------------------------------------------
  // 7. Clear Action
  // ---------------------------------------------------------
  clearBtn.addEventListener('click', async () => {
    if (confirm('Clear the document index and chat history?')) {
      try {
        await fetch('/api/clear', { method: 'DELETE' });
        chatMessages.innerHTML = `
          <div class="message assistant">
            <div class="avatar">🤖</div>
            <div class="bubble">Index cleared. Upload new PDF documents to start a fresh chat session.</div>
          </div>
        `;
        checkStatus();
      } catch (err) { alert('Failed to clear index'); }
    }
  });
});
