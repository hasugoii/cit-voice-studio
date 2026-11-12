'use strict';
(() => {
  document.documentElement.classList.add('with-js');
  const audios = Array.from(document.querySelectorAll('audio[id]'));
  const buttons = Array.from(document.querySelectorAll('[data-play]'));
  const status = document.querySelector('#audio-status');
  const format = n => { const s = Math.max(0, Math.floor(Number(n) || 0)); return `${String(Math.floor(s / 60)).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`; };
  const paint = audio => {
    for (const b of buttons.filter(b => b.dataset.play === audio.id)) {
      b.setAttribute('aria-pressed', String(!audio.paused));
      b.querySelector('[data-play-icon]').textContent = audio.paused ? '▶' : 'Ⅱ';
      b.querySelector('[data-play-text]').textContent = audio.paused ? 'Nghe mẫu' : 'Tạm dừng';
      b.setAttribute('aria-label', `${audio.paused ? 'Phát' : 'Tạm dừng'} mẫu ${audio.id === 'demo-male' ? 'Hải Đăng' : 'Trúc Ly'}`);
    }
    document.querySelectorAll(`[data-wave="${audio.id}"]`).forEach(w => w.classList.toggle('playing', !audio.paused));
    document.querySelectorAll(`[data-time="${audio.id}"]`).forEach(t => { t.textContent = `${format(audio.currentTime)} / ${format(Number.isFinite(audio.duration) ? audio.duration : 5)}`; });
  };
  document.querySelectorAll('.waveform').forEach((wave, index) => {
    for (let i = 0; i < 62; i++) {
      const bar = document.createElement('i');
      bar.style.height = `${12 + Math.abs(Math.sin(i * 1.43 + index) * Math.cos(i * .37)) * 50}px`;
      bar.style.setProperty('--delay',`${(i % 7) * -.13}s`);wave.append(bar);
    }
  });
  let playbackGeneration=0;
  for (const audio of audios) {
    for (const name of ['play','pause','ended','timeupdate','loadedmetadata']) audio.addEventListener(name, () => paint(audio));
    audio.addEventListener('ended', () => { if (audios.every(a => a.paused)) status.textContent='Đã nghe xong bản mẫu. Bạn có thể chọn giọng khác để so sánh.'; });
    audio.addEventListener('error', () => { status.textContent='Chưa tải được bản mẫu. Kiểm tra kết nối rồi thử lại.';status.classList.add('error');paint(audio); });
  }
  for (const b of buttons) {
    const audio = document.getElementById(b.dataset.play);
    if (!(audio instanceof HTMLMediaElement)) continue;
    b.disabled=false;
    b.addEventListener('click', async () => {
      const generation=++playbackGeneration;
      status.classList.remove('error');
      if (!audio.paused) { audio.pause(); return; }
      for (const other of audios) if (other !== audio) other.pause();
      b.disabled=true;
      try { await audio.play();if(generation!==playbackGeneration)return;status.textContent=`Đang nghe ${audio.id === 'demo-male' ? 'Hải Đăng' : 'Trúc Ly'} · Âm thanh tổng hợp bằng AI.`; }
      catch { if(generation!==playbackGeneration)return;status.textContent='Không phát được bản mẫu. Hãy thử lại hoặc kiểm tra cài đặt âm thanh của trình duyệt.';status.classList.add('error'); }
      finally { b.disabled=false;paint(audio); }
    });
  }
  const form=document.querySelector('#access-form');
  const submit=document.querySelector('#request-submit');
  const result=document.querySelector('#request-status');
  let submitting=false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || !form.reportValidity()) return;
    const data=new FormData(form);
    const payload={name:String(data.get('name')||'').trim(),email:String(data.get('email')||'').trim(),purpose:String(data.get('purpose')||'').trim(),website:String(data.get('website')||'')};
    if (!payload.name) { result.textContent='Vui lòng nhập họ và tên.';result.classList.add('error');return; }
    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),20000);
    submitting=true;submit.disabled=true;result.classList.remove('error');result.textContent='Đang gửi yêu cầu…';
    try {
      const response=await fetch('/saas/api/access-requests',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'omit',signal:controller.signal,body:JSON.stringify(payload)});
      let body;try { body=await response.json(); } catch { throw new Error('Chưa nhận được phản hồi từ máy chủ. Vui lòng thử lại.'); }
      if (!response.ok || body.ok !== true) {
        const message=typeof body.detail==='string' ? body.detail : response.status===422 ? 'Kiểm tra lại tên, email và độ dài nội dung.' : 'Chưa gửi được yêu cầu. Vui lòng thử lại sau.';
        throw new Error(message);
      }
      result.textContent=typeof body.message==='string' ? body.message : 'Đã ghi nhận yêu cầu. Quản trị viên sẽ xem nhu cầu của bạn.';form.reset();
    } catch (error) { result.textContent=error?.name==='AbortError' ? 'Kết nối đang chậm. Vui lòng thử lại sau.' : error instanceof Error ? error.message : 'Kết nối bị gián đoạn. Vui lòng thử lại.';result.classList.add('error'); }
    finally { clearTimeout(timeout);submitting=false;submit.disabled=false; }
  });
})();
