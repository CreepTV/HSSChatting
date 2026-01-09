(function(){
  const usersDiv = document.getElementById('users');
  const messagesDiv = document.getElementById('messages');
  const msgInput = document.getElementById('msg');
  const sendBtn = document.getElementById('send');
  const meSpan = document.getElementById('me');
  const channelsDiv = document.querySelector('.channels');
  const channelLabel = document.getElementById('channel-label');

  const storedNick = localStorage.getItem('hss_nick');
  let nick = storedNick || prompt('Dein Nickname für den Chat', storedNick || 'Gast');
  if(!nick) nick = 'Gast';
  let myName = nick;
  let currentChannel = 'all'; // 'all' or username

  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');

  const messages = { all: [] }; // messages['all'] and messages['id']

  const avatars = {}; // id -> avatar url
  const users = {};   // id -> username
  let myId = null;
  const avatarFile = document.getElementById('avatar-file');
  const avatarPreview = document.getElementById('avatar-preview');
  const uploadAvatarBtn = document.getElementById('upload-avatar');
  const removeAvatarBtn = document.getElementById('remove-avatar');
  const meAvatarImg = document.getElementById('me-avatar');

  // load cached avatar (fallback)
  const cachedAvatar = localStorage.getItem('hss_avatar');
  if(cachedAvatar){ setMeAvatar(cachedAvatar); }

  function setMeAvatar(url){
    if(url){ meAvatarImg.src = url; meAvatarImg.style.display = 'inline-block'; }
    else { meAvatarImg.src = ''; meAvatarImg.style.display = 'none'; }
  }

  function formatTime(ts){ try{ const d = new Date(ts); return d.toLocaleTimeString(); }catch(e){ return ''; } }

  function renderChannel(channel){
    messagesDiv.innerHTML = '';
    const list = messages[channel] || [];
    list.forEach(m=>{
      const el = document.createElement('div');
      if(m.user === '_system'){
        el.className = 'msg system';
        const meta = document.createElement('div'); meta.className='meta';
        meta.textContent = `${formatTime(m.ts)} · System`;
        el.appendChild(meta);
        const body = document.createElement('div'); body.textContent = m.text; el.appendChild(body);
      } else {
        const isOwn = (m.user_id === myId);
        el.className = 'msg ' + (isOwn ? 'own' : 'other');
        const meta = document.createElement('div'); meta.className = 'meta';
        const who = document.createElement('div'); who.className='who'; who.textContent = isOwn ? (m.user + ' (du)') : m.user;
        const right = document.createElement('div'); right.className='time'; right.textContent = formatTime(m.ts);
        // show small avatar in message meta if available (by id)
        const avatarUrl = avatars[m.user_id];
        if(avatarUrl){
          const aimg = document.createElement('img'); aimg.className='avatar-img'; aimg.src = avatarUrl; meta.appendChild(aimg);
        }
        meta.appendChild(who); meta.appendChild(right);
        if(m.private){
          const pb = document.createElement('span'); pb.className='private-badge'; pb.textContent='Privat'; meta.appendChild(pb);
        }
        const body = document.createElement('div'); body.textContent = m.text;
        el.appendChild(meta);
        el.appendChild(body);
      }
      messagesDiv.appendChild(el);
    });
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    const title = channel === 'all' ? 'Hauptchat' : `Privat: ${users[channel] || channel}`;
    channelLabel.textContent = title;
    // update active channel button
    Array.from(document.querySelectorAll('.channel-btn')).forEach(b=>{
      const active = b.dataset.channel === channel;
      b.classList.toggle('active', active);
      if(active){
        // clear unread badge
        const badge = b.querySelector('.badge'); if(badge) badge.remove(); b.dataset.unread = 0;
      }
    });
  }

  function addMessageTo(channel, msg){
    messages[channel] = messages[channel] || [];
    messages[channel].push(msg);
  }

  ws.addEventListener('open', ()=>{ ws.send(JSON.stringify({type:'join', user:nick})); });

  ws.addEventListener('message', (ev)=>{
    try{
      const data = JSON.parse(ev.data);
      if(data.type === 'message'){
        if(data.private){
          // private: determine other id (channel key by id)
          const other = (data.user_id === myId) ? data.to : data.user_id;
          // ignore messages that would create a self-entry in the sidebar
          if(other === myId) { return; }
          addMessageTo(other, data);
          // find or create a sidebar user button by id and show unread there
          let userBtn = Array.from(usersDiv.querySelectorAll('button')).find(b => b.dataset && b.dataset.id === other);
          const otherName = data.to_user || data.user || users[other] || other;
          if(!userBtn){
            userBtn = document.createElement('button');
            userBtn.dataset.id = other;
            const avatarUrl = avatars[other];
            if(avatarUrl){
              const img = document.createElement('img'); img.className='avatar-img'; img.src = avatarUrl; userBtn.appendChild(img);
            } else {
              const av = document.createElement('div'); av.className='avatar'; av.textContent = (otherName||'').slice(0,2).toUpperCase(); userBtn.appendChild(av);
            }
            const txt = document.createElement('div'); txt.textContent = otherName; userBtn.appendChild(txt);
            const b = document.createElement('span'); b.className='badge'; userBtn.appendChild(b);
            userBtn.addEventListener('click', ()=>{ currentChannel = other; renderChannel(currentChannel); ws.send(JSON.stringify({type:'history', channel:other})); const bb = userBtn.querySelector('.badge'); if(bb) bb.remove(); userBtn.dataset.unread = 0; });
            usersDiv.appendChild(userBtn);
          } else {
            // if existing, maybe update avatar if available
            const avatarUrl = avatars[other];
            const existingImg = userBtn.querySelector('img.avatar-img');
            if(avatarUrl && !existingImg){
              const avDiv = userBtn.querySelector('.avatar'); if(avDiv) avDiv.remove();
              const img = document.createElement('img'); img.className='avatar-img'; img.src = avatarUrl; userBtn.insertBefore(img, userBtn.firstChild);
            } else if(!avatarUrl && existingImg){
              existingImg.remove();
              const avDiv = document.createElement('div'); avDiv.className='avatar'; avDiv.textContent = (otherName||'').slice(0,2).toUpperCase(); userBtn.insertBefore(avDiv, userBtn.firstChild);
            } else if(avatarUrl && existingImg){ existingImg.src = avatarUrl; }
            // also ensure label is up to date
            const label = userBtn.querySelector('div'); if(label) label.textContent = otherName;
          }
          // if not currently viewing that channel, show unread badge
          if(currentChannel !== other){
            const count = parseInt(userBtn.dataset.unread||0) + 1; userBtn.dataset.unread = count;
            let badge = userBtn.querySelector('.badge'); if(!badge){ badge = document.createElement('span'); badge.className='badge'; userBtn.appendChild(badge); }
            badge.textContent = String(count);
          }
          if(currentChannel === other) renderChannel(currentChannel);
        } else {
          // public message
          addMessageTo('all', data);
          if(currentChannel === 'all') renderChannel('all');
        }
      } else if(data.type === 'user_list'){
        // update users list (array of objects {id, user, avatar})
        usersDiv.innerHTML = '';
        data.users.forEach(item=>{
          const id = item.id;
          const u = item.user || '';
          const avatar = item.avatar || null;
          // store in maps
          users[id] = u;
          avatars[id] = avatar;
          // skip showing self in the list
          if(id === myId) {
            if(avatar){ setMeAvatar(avatar); localStorage.setItem('hss_avatar', avatar); }
            return;
          }

          const existing = Array.from(usersDiv.querySelectorAll('button')).find(b => b.dataset && b.dataset.id === id);
          if(existing){
            // update avatar if changed
            const existingImg = existing.querySelector('img.avatar-img');
            if(avatar && !existingImg){ const avDiv = existing.querySelector('.avatar'); if(avDiv) avDiv.remove(); const img = document.createElement('img'); img.className='avatar-img'; img.src = avatar; existing.insertBefore(img, existing.firstChild); }
            else if(!avatar && existingImg){ existingImg.remove(); const avDiv = document.createElement('div'); avDiv.className='avatar'; avDiv.textContent = u.slice(0,2).toUpperCase(); existing.insertBefore(avDiv, existing.firstChild); }
            else if(avatar && existingImg){ existingImg.src = avatar; }
            return;
          }

          const btn = document.createElement('button'); btn.dataset.id = id;
          if(avatar){ const img = document.createElement('img'); img.className='avatar-img'; img.src = avatar; btn.appendChild(img); }
          else { const av = document.createElement('div'); av.className='avatar'; av.textContent = u.slice(0,2).toUpperCase(); btn.appendChild(av); }
          const txt = document.createElement('div'); txt.textContent = u; btn.appendChild(txt);
          const badge = document.createElement('span'); badge.className='badge hidden'; btn.appendChild(badge);
          btn.addEventListener('click', ()=>{ 
            currentChannel = id; 
            renderChannel(currentChannel);
            // request DM history from server (channel by id)
            ws.send(JSON.stringify({type:'history', channel:id}));
            // clear unread badge on this user
            badge.remove(); btn.dataset.unread = 0; 
          });
          usersDiv.appendChild(btn);
        });
      } else if(data.type === 'joined'){
        myName = data.user; myId = data.id; meSpan.textContent = myName; localStorage.setItem('hss_nick', myName); addMessageTo('all', {user:'_system', text:`Dein Nick ist jetzt: ${myName}`, ts:data.ts||new Date().toISOString()});
        // set avatar if present
        const av = avatars[myId] || localStorage.getItem('hss_avatar'); if(av){ setMeAvatar(av); }
        renderChannel(currentChannel);
      } else if(data.type === 'renamed'){
        // rename applies to the current client
        myName = data.user; meSpan.textContent = myName; localStorage.setItem('hss_nick', myName); addMessageTo('all', {user:'_system', text:`${data.old} heißt jetzt ${data.user}`, ts:data.ts||new Date().toISOString()});
        const av2 = avatars[myId] || localStorage.getItem('hss_avatar'); if(av2){ setMeAvatar(av2); }
        renderChannel(currentChannel);
      } else if(data.type === 'history'){
        const ch = data.channel || 'all';
        messages[ch] = data.messages || [];
        if(currentChannel === ch) renderChannel(ch);
      }
    }catch(e){ console.error(e); }
  });


  // Settings Popup
  const settingsBtn = document.getElementById('settings-btn');
  const settingsPopup = document.getElementById('settings-popup');
  const closeSettings = document.getElementById('close-settings');
  const nickInput = document.getElementById('set-nick');
  const saveNickBtn = document.getElementById('save-nick');

  // Verbesserte Nickname-Input-UX
  const nickClear = document.getElementById('nick-clear');
  function updateClearBtn() {
    if(nickInput.value.length > 0) {
      nickClear.style.display = '';
    } else {
      nickClear.style.display = 'none';
    }
  }
  nickInput.addEventListener('input', updateClearBtn);
  nickClear.addEventListener('click', ()=>{ nickInput.value = ''; updateClearBtn(); nickInput.focus(); });
  // Accessible modal open/close with focus management
  let _prevFocus = null;
  function _onSettingsKey(e){
    if(e.key === 'Escape') closeSettingsPopup();
    // simple focus trap (Tab cycles within dialog)
    if(e.key === 'Tab' && document.activeElement){
      const focusable = Array.from(settingsPopup.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter(el => !el.hasAttribute('disabled'));
      if(focusable.length === 0) return;
      const idx = focusable.indexOf(document.activeElement);
      if(e.shiftKey && idx === 0){ focusable[focusable.length-1].focus(); e.preventDefault(); }
      else if(!e.shiftKey && idx === focusable.length-1){ focusable[0].focus(); e.preventDefault(); }
    }
  }
  function openSettings(){
    _prevFocus = document.activeElement;
    settingsPopup.classList.add('open');
    settingsPopup.setAttribute('aria-hidden','false');
    settingsBtn.setAttribute('aria-expanded','true');
    nickInput.value = localStorage.getItem('hss_nick') || nick;
    updateClearBtn();
    document.addEventListener('keydown', _onSettingsKey);
    // focus first input
    setTimeout(()=>{ nickInput.focus(); }, 50);
  }
  function closeSettingsPopup(){
    settingsPopup.classList.remove('open');
    settingsPopup.setAttribute('aria-hidden','true');
    settingsBtn.setAttribute('aria-expanded','false');
    document.removeEventListener('keydown', _onSettingsKey);
    if(_prevFocus && _prevFocus.focus) _prevFocus.focus();
  }
  settingsBtn.addEventListener('click', openSettings);
  closeSettings.addEventListener('click', closeSettingsPopup);
  settingsPopup.addEventListener('click', (e)=>{ if(e.target === settingsPopup) closeSettingsPopup(); });

  saveNickBtn.addEventListener('click', ()=>{
    const newNick = (nickInput.value || '').trim(); if(!newNick) return;
    ws.send(JSON.stringify({type:'rename', user:newNick}));
    closeSettingsPopup();
  });
  nickInput.addEventListener('keydown', (e)=>{ if(e.key === 'Enter') saveNickBtn.click(); });

  // Avatar upload handlers
  avatarFile.addEventListener('change', (e)=>{
    const f = e.target.files && e.target.files[0];
    if(!f) return;
    if(f.size > 2*1024*1024){ alert('Datei zu groß (max. 2 MB)'); avatarFile.value = ''; return; }
    const url = URL.createObjectURL(f);
    avatarPreview.src = url; avatarPreview.style.display = 'block';
    uploadAvatarBtn.style.display = ''; removeAvatarBtn.style.display = '';
  });

  uploadAvatarBtn.addEventListener('click', async ()=>{
    const f = avatarFile.files && avatarFile.files[0];
    if(!f){ alert('Wähle zuerst eine Datei aus'); return; }
    if(!myId){ alert('Bitte verbinde dich zuerst'); return; }
    uploadAvatarBtn.disabled = true; uploadAvatarBtn.textContent = 'Hochladen...';
    try{
      const fd = new FormData(); fd.append('file', f);
      const res = await fetch('/upload-avatar', { method: 'POST', body: fd });
      const text = await res.text();
      if(!res.ok){
        try{ const j = JSON.parse(text); alert(j.detail || j.message || 'Upload fehlgeschlagen'); }
        catch(e){ alert('Upload fehlgeschlagen: ' + text); }
        return;
      }
      const j = JSON.parse(text);
      // store by id (not by name) so client/server mappings align
      if(myId) { avatars[myId] = j.url; }
      localStorage.setItem('hss_avatar', j.url); setMeAvatar(j.url);
      // update own preview and any existing sidebar button for this id
      avatarPreview.src = j.url; avatarPreview.style.display = 'block';
      uploadAvatarBtn.style.display = 'none'; removeAvatarBtn.style.display = '';
      // update any existing user button for this id
      const myBtn = Array.from(usersDiv.querySelectorAll('button')).find(b => b.dataset && b.dataset.id === myId);
      if(myBtn){ const existingImg = myBtn.querySelector('img.avatar-img'); if(existingImg){ existingImg.src = j.url; } else { const avDiv = myBtn.querySelector('.avatar'); if(avDiv) avDiv.remove(); const img = document.createElement('img'); img.className='avatar-img'; img.src = j.url; myBtn.insertBefore(img, myBtn.firstChild); } }
      avatarFile.value = '';
    }catch(e){ alert('Upload fehlgeschlagen: ' + (e && e.message ? e.message : String(e))); }
    uploadAvatarBtn.disabled = false; uploadAvatarBtn.textContent = 'Hochladen';
  });

  removeAvatarBtn.addEventListener('click', async ()=>{
    if(!myId) return;
    try{
      const fd = new FormData();
      const res = await fetch('/remove-avatar', { method: 'POST', body: fd });
      const text = await res.text();
      if(!res.ok){ try{ const j = JSON.parse(text); alert(j.detail || j.message || 'Entfernen fehlgeschlagen'); }catch(e){ alert('Entfernen fehlgeschlagen: '+text); } return; }
      if(myId){ avatars[myId] = null; }
      localStorage.removeItem('hss_avatar'); setMeAvatar(null); avatarPreview.src = ''; avatarPreview.style.display='none'; uploadAvatarBtn.style.display='none'; removeAvatarBtn.style.display='none';
    }catch(e){ alert('Entfernen fehlgeschlagen'); }
  });

  // ensure preview shows stored avatar when opening settings
  const prevOpenSettings = openSettings;
  openSettings = function(){
    prevOpenSettings();
    const av = (myId && avatars[myId]) || localStorage.getItem('hss_avatar');
    if(av){ avatarPreview.src = av; avatarPreview.style.display='block'; removeAvatarBtn.style.display=''; uploadAvatarBtn.style.display='none'; }
    else { avatarPreview.src = ''; avatarPreview.style.display='none'; removeAvatarBtn.style.display='none'; uploadAvatarBtn.style.display='none'; }
  };

  // send message

    sendBtn.addEventListener('click', ()=>{
      const text = msgInput.value.trim(); if(!text) return;
      const to = currentChannel || 'all';
      if(to !== 'all' && to === myId) return; // nicht an sich selbst senden
      ws.send(JSON.stringify({type:'message', text, to}));
      msgInput.value = '';
    });

  msgInput.addEventListener('keydown', (e)=>{ if(e.key === 'Enter') sendBtn.click(); });

  // channel button (main)
  document.querySelector('.channel-btn[data-channel="all"]').addEventListener('click', ()=>{ currentChannel='all'; renderChannel('all'); ws.send(JSON.stringify({type:'history', channel:'all'})); });

  window.addEventListener('beforeunload', ()=>{ try{ ws.send(JSON.stringify({type:'leave'})); }catch(e){} ws.close(); });
})();
```