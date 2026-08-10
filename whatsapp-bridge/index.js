/**
 * Bridge WhatsApp (Baileys) untuk Sales Canvas Bot.
 *
 * Alur:
 *   1. Jalankan:  node index.js
 *   2. Scan QR yang muncul di terminal dengan WhatsApp > Perangkat tertaut.
 *   3. Pesan (foto struk / perintah) diteruskan ke server Python (FastAPI).
 *   4. Balasan dari Python dikirim kembali ke pengguna.
 *
 * Env yang dibaca:
 *   PYTHON_API_URL        default http://127.0.0.1:8000
 *   BRIDGE_WEBHOOK_SECRET harus sama dengan .env di project Python
 *   BRIDGE_PORT           default 3100 (endpoint /send untuk pesan keluar)
 */
require('dotenv').config();
const express = require('express');
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, downloadMediaMessage } = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');

const PY_API = (process.env.PYTHON_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const SECRET = process.env.BRIDGE_WEBHOOK_SECRET || 'ganti-ini-dengan-string-acak';
const PORT = Number(process.env.BRIDGE_PORT || 3100);

// ---- endpoint kecil untuk mengirim pesan dari Python (fitur proaktif) ----
let sockRef = null;
const app = express();
app.use(express.json());
app.post('/send', async (req, res) => {
  const { to, text } = req.body || {};
  if (req.headers['x-secret'] !== SECRET) return res.status(401).json({ ok: false });
  if (!sockRef || !to || !text) return res.status(400).json({ ok: false });
  try {
    await sockRef.sendMessage(to, { text });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e) });
  }
});
app.get('/health', (req, res) => res.json({ ok: !!sockRef }));
app.listen(PORT, () => console.log(`[bridge] endpoint /send aktif di http://127.0.0.1:${PORT}`));

// ---------------------------------------------------------------------------

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState('auth');
  const sock = makeWASocket({ auth: state, browser: ['Sales Canvas', 'Chrome', '1.0'] });
  sockRef = sock;

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      // Baileys v6+: QR ditampilkan manual lewat event connection.update
      qrcode.generate(qr, { small: true }, (code) => console.log(code));
      console.log('\n📲 Scan QR di atas dengan WhatsApp > Pengaturan > Perangkat tertaut\n');
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = code !== DisconnectReason.loggedOut;
      console.log(`[bridge] koneksi tertutup (${code}), reconnect=${shouldReconnect}`);
      if (shouldReconnect) start();
    } else if (connection === 'open') {
      console.log('[bridge] ✅ WhatsApp terhubung! Kirim foto struk dari nomor mana pun.');
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const msg of messages) {
      if (msg.key.fromMe || !msg.message) continue;
      const sender = msg.key.remoteJid; // "62xxx@s.whatsapp.net"
      try {
        if (msg.message.imageMessage) {
          const buffer = await downloadMediaMessage(msg, 'buffer', {}, { logger: undefined });
          const form = new FormData();
          form.append('sender', sender);
          form.append('type', 'image');
          form.append('caption', msg.message.imageMessage.caption || '');
          form.append('secret', SECRET);
          form.append('image', new Blob([buffer], { type: 'image/jpeg' }), 'struk.jpg');
          console.log('[bridge] 📷 foto diterima dari', sender, `(${buffer.length} bytes)`);
          const res = await fetch(`${PY_API}/api/whatsapp/inbound`, { method: 'POST', body: form });
          const data = await res.json();
          if (data && data.reply) await sock.sendMessage(sender, { text: data.reply });
        } else {
          const textMsg = msg.message.conversation
            || msg.message.extendedTextMessage?.text
            || '';
          if (!textMsg.trim()) continue;
          const form = new FormData();
          form.append('sender', sender);
          form.append('type', 'text');
          form.append('text', textMsg.trim());
          form.append('secret', SECRET);
          console.log('[bridge] 💬 teks diterima dari', sender, ':', textMsg.trim());
          const res = await fetch(`${PY_API}/api/whatsapp/inbound`, { method: 'POST', body: form });
          const data = await res.json();
          if (data && data.reply) await sock.sendMessage(sender, { text: data.reply });
        }
      } catch (e) {
        console.error('[bridge] error memproses pesan:', e);
      }
    }
  });
}

start().catch((e) => console.error('[bridge] fatal:', e));
