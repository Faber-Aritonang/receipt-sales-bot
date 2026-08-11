/**
 * Bridge WhatsApp (Baileys) untuk Sales Canvas Bot.
 *
 * Alur:
 *   1. Jalankan:  node index.js   (atau npm start)
 *   2. Scan QR yang muncul di terminal dengan WhatsApp > Perangkat tertaut.
 *   3. Pesan (foto struk / perintah / ketukan tombol) diteruskan ke server Python (FastAPI).
 *   4. Balasan dari Python dikirim kembali ke pengguna.
 *
 * Tombol & menu:
 *   Ketik "menu" / "tombol" / "bantuan" -> bot mengirim tombol perintah interaktif
 *   (fallback: daftar bernomor — balas dengan angka 1-7).
 *
 * Env yang dibaca:
 *   PYTHON_API_URL        default http://127.0.0.1:8000
 *   BRIDGE_WEBHOOK_SECRET harus sama dengan .env di project Python
 *   BRIDGE_PORT           default 3100 (endpoint /send untuk pesan keluar)
 */
'use strict';

require('dotenv').config();
const path = require('path');
const fs = require('fs');
const express = require('express');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  downloadMediaMessage,
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');

const PY_API = (process.env.PYTHON_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const SECRET = process.env.BRIDGE_WEBHOOK_SECRET || 'ganti-ini-dengan-string-acak';
const PORT = Number(process.env.BRIDGE_PORT || 3100);

/** Lokasi file QR PNG (ditimpa tiap QR baru, dihapus saat sudah terhubung). */
const QR_PNG = path.join(__dirname, 'qr.png');

// ---------------------------------------------------------------------------
// Menu & tombol
// ---------------------------------------------------------------------------

/** Tombol menu: id dikirim ke Python sebagai /<id>. */
const MENU = [
  { id: 'laporanharian', label: '📆 Laporan Harian' },
  { id: 'laporanmingguan', label: '🗓️ Mingguan' },
  { id: 'laporanbulanan', label: '📅 Bulanan' },
  { id: 'produkterlaris', label: '🏆 Produk Terlaris' },
  { id: 'total', label: '💼 Total Penjualan' },
  { id: 'export', label: '📥 Ekspor Excel' },
  { id: 'bantuan', label: '❓ Bantuan' },
];

/** Pemetaan angka fallback (1..N) -> perintah. */
const NUM_TO_CMD = {};
MENU.forEach((b, i) => {
  NUM_TO_CMD[String(i + 1)] = b.id;
});
const NUM_RE = new RegExp(`^[1-${MENU.length}]$`);

/** Teks menu bernomor (dipakai bila tombol interaktif tidak tampil). */
function menuText() {
  return [
    '🤖 Sales Canvas Bot',
    '',
    'Ketik angka di bawah, ketuk tombol, atau kirim foto struk:',
    ...MENU.map((b, i) => `${i + 1}. ${b.label}`),
  ].join('\n');
}

/**
 * Buka bungkusan pesan sementara (disappearing / view-once / document caption).
 * Baileys membungkus pesan seperti ini di dalam ephemeralMessage; tanpa ini
 * foto/teks dari chat ber-pesan-sementara diabaikan begitu saja.
 */
function unwrapEphemeral(message) {
  let m = message;
  while (m && (m.ephemeralMessage || m.viewOnceMessage || m.documentWithCaptionMessage)) {
    m = (m.ephemeralMessage || m.viewOnceMessage || m.documentWithCaptionMessage).message;
  }
  return m;
}

/** Ambil id tombol yang diketuk user (native flow / tombol lama). */
function getButtonId(content) {
  const ir = content.interactiveResponseMessage;
  const nf = ir && ir.nativeFlowResponseMessage;
  if (nf) {
    try {
      const params = JSON.parse(nf.paramsJson || '{}');
      if (params.id) return params.id;
    } catch (_) {
      /* lanjut ke fallback */
    }
    return nf.selectedButtonId || null;
  }
  const br = content.buttonsResponseMessage;
  return br ? br.selectedButtonId || null : null;
}

/** Kirim teks menu + tombol interaktif (quick_reply native flow). */
async function sendMenu(sock, jid) {
  // 1) teks bernomor selalu dikirim (fallback bila tombol tidak tampil)
  await sock.sendMessage(jid, { text: menuText() });
  // 2) tombol interaktif
  try {
    await sock.sendMessage(jid, {
      interactiveMessage: {
        header: { title: '🤖 Sales Canvas Bot' },
        body: { text: 'Pilih perintah:' },
        nativeFlowMessage: {
          buttons: MENU.map((b) => ({
            name: 'quick_reply',
            buttonParamsJson: JSON.stringify({ display_text: b.label, id: b.id }),
          })),
        },
      },
    });
  } catch (e) {
    console.error('[bridge] tombol interaktif gagal dikirim (pakai angka saja):', e.message);
  }
}

/** Teruskan teks perintah ke Python, lalu kirim balasannya ke pengguna. */
async function forwardText(sock, jid, text) {
  const form = new FormData();
  form.append('sender', jid);
  form.append('type', 'text');
  form.append('text', text);
  form.append('secret', SECRET);
  const res = await fetch(`${PY_API}/api/whatsapp/inbound`, { method: 'POST', body: form });
  const data = await res.json();
  if (data && data.reply) await sock.sendMessage(jid, { text: data.reply });
}

/** Unduh foto struk dan teruskan ke Python untuk di-OCR. */
async function handleImage(sock, msg, content, sender) {
  // ctx.logger diperlukan: tanpa logger, media yang butuh re-upload (view-once
  // / pesan sementara) membuat Baileys crash saat memanggil ctx.logger.info.
  const buffer = await downloadMediaMessage(msg, 'buffer', {}, { logger: console });
  const caption =
    (content.imageMessage && content.imageMessage.caption) ||
    (content.documentMessage && content.documentMessage.caption) ||
    '';
  const form = new FormData();
  form.append('sender', sender);
  form.append('type', 'image');
  form.append('caption', caption);
  form.append('secret', SECRET);
  form.append('image', new Blob([buffer], { type: 'image/jpeg' }), 'struk.jpg');
  console.log('[bridge] 📷 foto diterima dari', sender, `(${buffer.length} bytes)`);
  const res = await fetch(`${PY_API}/api/whatsapp/inbound`, { method: 'POST', body: form });
  const data = await res.json();
  if (data && data.reply) await sock.sendMessage(sender, { text: data.reply });
}

// ---------------------------------------------------------------------------
// Endpoint kecil untuk mengirim pesan dari Python (fitur proaktif)
// ---------------------------------------------------------------------------

let sockRef = null;

/** Endpoint kecil agar Python bisa mengirim pesan ke WhatsApp (fitur proaktif). */
function startExpress() {
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

  // QR sebagai gambar: /qr.png (PNG mentah) dan /qr (halaman dengan auto-refresh)
  app.get('/qr.png', (req, res) => {
    if (!fs.existsSync(QR_PNG)) {
      return res.status(404).type('text/plain').send('QR belum tersedia — tunggu beberapa detik.');
    }
    res.sendFile(QR_PNG);
  });
  app.get('/qr', (req, res) => {
    const html = `<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scan QR — Sales Canvas Bot</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0b141a; color: #e9edef; display: flex; flex-direction: column; align-items: center; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 6px; }
  p { color: #8696a0; margin: 4px 0 20px; text-align: center; }
  img { width: min(320px, 80vw); height: auto; border-radius: 12px; background: #fff; padding: 8px; box-shadow: 0 8px 30px rgba(0,0,0,.5); }
  .badge { background: #00a884; color: #fff; padding: 6px 14px; border-radius: 999px; font-size: 13px; margin-top: 18px; }
</style>
</head>
<body>
  <h1>📲 Scan QR WhatsApp</h1>
  <p>Buka <b>WhatsApp → Pengaturan → Perangkat tertaut</b> lalu scan gambar di bawah ini.<br>Halaman ini otomatis memuat ulang QR setiap beberapa detik.</p>
  <img id="qr" src="/qr.png" alt="QR Code">
  <div class="badge">Menunggu scan…</div>
<script>
  const img = document.getElementById('qr');
  function refresh() { img.src = '/qr.png?t=' + Date.now(); }
  setInterval(refresh, 4000);
</script>
</body>
</html>`;
    res.type('html').send(html);
  });

  app.listen(PORT, () => console.log(`[bridge] endpoint /send aktif di http://127.0.0.1:${PORT}`));
}

// ---------------------------------------------------------------------------
// Koneksi WhatsApp
// ---------------------------------------------------------------------------

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState('auth');
  const sock = makeWASocket({ auth: state, browser: ['Sales Canvas', 'Chrome', '1.0'] });
  sockRef = sock;

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      // 1) QR teks ASCII di terminal
      qrcode.generate(qr, { small: true }, (code) => console.log(code));
      // 2) QR sebagai gambar PNG — bisa discan dari layar / dibuka di browser
      QRCode.toFile(QR_PNG, qr, { width: 480, margin: 2 })
        .then(() =>
          console.log(
            `[bridge] 🖼️ QR gambar tersimpan: ${path.join(__dirname, 'qr.png')}\n` +
            `[bridge] 📱 Atau buka di browser: http://127.0.0.1:${PORT}/qr`
          )
        )
        .catch((e) => console.error('[bridge] gagal simpan QR PNG:', e.message));
      console.log('\n📲 Scan QR di atas dengan WhatsApp > Pengaturan > Perangkat tertaut\n');
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = code !== DisconnectReason.loggedOut;
      console.log(`[bridge] koneksi tertutup (${code}), reconnect=${shouldReconnect}`);
      if (shouldReconnect) {
        // jeda agar tidak membanjiri server saat reconnect berulang
        setTimeout(() => start().catch((e) => console.error('[bridge] fatal reconnect:', e)), 3000);
      }
    } else if (connection === 'open') {
      // QR sudah tidak berlaku lagi — hapus gambar agar tidak discan ulang
      fs.rmSync(QR_PNG, { force: true });
      console.log('[bridge] ✅ WhatsApp terhubung! Kirim foto struk, atau ketik "menu" untuk tombol perintah.');
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const msg of messages) {
      if (msg.key.fromMe || !msg.message) continue;
      const sender = msg.key.remoteJid;
      // hanya chat 1:1 — abaikan status broadcast & grup
      // (jangan whitelist suffix @s.whatsapp.net: akun LID bisa memakai @lid)
      if (!sender || sender === 'status@broadcast' || sender.includes('@g.us')) continue;

      const content = unwrapEphemeral(msg.message);
      if (!content) continue;

      try {
        // 1) User mengetuk tombol menu
        const btnId = getButtonId(content);
        if (btnId) {
          console.log('[bridge] 🎛️ tombol', btnId, 'dari', sender);
          await forwardText(sock, sender, '/' + btnId);
          continue;
        }

        // 2) Foto struk / dokumen bergambar
        const isImage =
          content.imageMessage ||
          (content.documentMessage && (content.documentMessage.mimetype || '').startsWith('image/'));
        if (isImage) {
          await handleImage(sock, msg, content, sender);
          continue;
        }

        // 3) Teks biasa
        const textMsg = content.conversation || content.extendedTextMessage?.text || '';
        if (!textMsg.trim()) continue;
        const t = textMsg.trim().toLowerCase();

        // panggil menu / tombol / bantuan
        if (t === 'menu' || t === 'tombol' || t === 'bantuan' || t === '/menu' || t === '/bantuan') {
          await sendMenu(sock, sender);
          continue;
        }
        // fallback bernomor (1..N) bila tombol tidak tampil
        if (NUM_RE.test(t)) {
          console.log('[bridge] 🔢 menu angka', t, 'dari', sender);
          await forwardText(sock, sender, '/' + NUM_TO_CMD[t]);
          continue;
        }

        console.log('[bridge] 💬 teks diterima dari', sender, ':', textMsg.trim());
        await forwardText(sock, sender, textMsg.trim());
      } catch (e) {
        console.error('[bridge] error memproses pesan dari', sender, ':', e);
        try {
          await sock.sendMessage(sender, { text: '⚠️ Terjadi kesalahan saat memproses pesan. Coba lagi.' });
        } catch (_) {
          /* abaikan */
        }
      }
    }
  });
}

if (require.main === module) {
  startExpress();
  start().catch((e) => console.error('[bridge] fatal:', e));
}

module.exports = { MENU, NUM_TO_CMD, menuText, unwrapEphemeral, getButtonId, sendMenu };
