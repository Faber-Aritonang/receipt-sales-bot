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

const path = require('path');
const fs = require('fs');
// Pastikan .env yang dibaca adalah whatsapp-bridge/.env, bukan .env dari
// working directory saat `node index.js` dijalankan (mis. dari root project).
require('dotenv').config({ path: path.join(__dirname, '.env') });
const express = require('express');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  downloadMediaMessage,
  generateWAMessageFromContent,
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');

const PY_API = (process.env.PYTHON_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const SECRET = process.env.BRIDGE_WEBHOOK_SECRET || 'ganti-ini-dengan-string-acak';
const PORT = Number(process.env.BRIDGE_PORT || 3100);

/**
 * Whitelist nomor WhatsApp yang boleh memakai bot.
 *
 * Sumber:
 *   1. File whatsapp-bridge/allowed-numbers.json (jika ada) — dibuat/ diperbarui
 *      oleh perintah bot (/izinkan, /blokir) dan endpoint /admin/whitelist.
 *   2. Env WHATSAPP_ALLOWED_NUMBERS (format nomor internasional tanpa '+',
 *      dipisah koma) — dipakai sebagai nilai awal bila file belum ada.
 *
 * Kosong = SEMUA nomor boleh (kompatibel dengan setup lama).
 * Pesan dari perangkat sendiri (chat ke diri sendiri, fromMe=true) selalu
 * diproses tanpa perlu masuk whitelist.
 */
/**
 * Direktori data runtime (session auth/, whitelist, id pesan, QR). Default =
 * folder index.js; bisa di-override via env BRIDGE_DATA_DIR agar data bisa
 * disimpan di persistent disk (mis. deploy di Render, set BRIDGE_DATA_DIR ke
 * mount path disk).
 */
const DATA_DIR = process.env.BRIDGE_DATA_DIR || __dirname;

// Path file whitelist bisa di-override lewat env (dipakai test agar tidak
// menyentuh file asli).
const ALLOW_LIST_FILE =
  process.env.WHATSAPP_ALLOW_LIST_FILE || path.join(DATA_DIR, 'allowed-numbers.json');

function normalizeNumber(raw) {
  return String(raw || '').replace(/\D/g, '');
}

// nilai awal dari env, lalu ditimpa file jika ada
let allowedNumbers = new Set(
  (process.env.WHATSAPP_ALLOWED_NUMBERS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map(normalizeNumber)
);

try {
  const arr = JSON.parse(fs.readFileSync(ALLOW_LIST_FILE, 'utf8'));
  if (Array.isArray(arr)) allowedNumbers = new Set(arr.map(normalizeNumber).filter(Boolean));
} catch (_) {
  /* file belum ada / rusak -> pakai nilai env */
}

function saveAllowList() {
  try {
    fs.writeFileSync(ALLOW_LIST_FILE, JSON.stringify([...allowedNumbers], null, 0));
  } catch (e) {
    console.error('[bridge] gagal simpan whitelist:', e.message);
  }
}

/** Ambil angka telpon dari JID (mis. 628123456789@s.whatsapp.net -> 628123456789). */
function numberFromJid(jid) {
  if (!jid) return '';
  return jid.split('@')[0].replace(/\D/g, '');
}

/** Apakah nomor pengirim boleh memakai bot? (kosong = semua boleh) */
function isAllowedSender(jid) {
  if (!allowedNumbers.size) return true;
  return allowedNumbers.has(numberFromJid(jid));
}

/** Apakah format nomor masuk akal (8–15 digit, tanpa kode area yang aneh)? */
function validPhoneNumber(n) {
  return n.length >= 8 && n.length <= 15;
}

/** Tambah nomor ke whitelist (persisten). */
function waWhitelistAdd(number) {
  const n = normalizeNumber(number);
  if (!n) return { ok: false, error: 'nomor tidak valid' };
  if (!validPhoneNumber(n)) {
    return { ok: false, error: 'format nomor tidak masuk akal (8–15 digit)' };
  }
  allowedNumbers.add(n);
  saveAllowList();
  return { ok: true, allowed: [...allowedNumbers] };
}

/** Hapus nomor dari whitelist (persisten). */
function waWhitelistRemove(number) {
  const n = normalizeNumber(number);
  if (!n) return { ok: false, error: 'nomor tidak valid' };
  if (!allowedNumbers.has(n)) {
    return { ok: false, error: 'nomor tidak ada di daftar' };
  }
  // JANGAN izinkan menghapus nomor terakhir: set kosong = mode "semua boleh",
  // sehingga blokir tanpa sengaja akan membuka bot untuk semua orang.
  if (allowedNumbers.size <= 1) {
    return {
      ok: false,
      error: 'tidak bisa menghapus nomor terakhir — bot akan terbuka untuk semua orang',
    };
  }
  allowedNumbers.delete(n);
  saveAllowList();
  return { ok: true, allowed: [...allowedNumbers] };
}

/** Daftar nomor yang saat ini diizinkan. */
function waWhitelistList() {
  return { ok: true, allowed: [...allowedNumbers] };
}

/**
 * Proteksi halaman QR di browser.
 * QR_PASSWORD kosong  -> tanpa login (kompatibel dengan setup lama).
 * QR_PASSWORD terisi  -> /qr & /qr.png butuh password (cookie httpOnly 24 jam).
 * Bisa juga diakses via URL: /qr?token=PASSWORD.
 */
const QR_PASSWORD = process.env.QR_PASSWORD || '';
const QR_COOKIE = 'qr_ok';
const QR_COOKIE_MAXAGE = 24 * 3600 * 1000; // 24 jam

/** Lokasi file QR PNG (ditimpa tiap QR baru, dihapus saat sudah terhubung). */
const QR_PNG = path.join(DATA_DIR, 'qr.png');

/**
 * Lokasi session WhatsApp. Absolut terhadap DATA_DIR, bukan working
 * directory — agar `node index.js` dari direktori mana pun tetap memakai
 * session yang sama (cara ini juga dipakai untuk dotenv).
 */
const AUTH_DIR = path.join(DATA_DIR, 'auth');

/**
 * File persist id pesan yang sudah ditangani. Dipakai agar pesan lama yang
 * di-deliver ulang WhatsApp setelah restart/reconnect TIDAK diproses lagi
 * (penyebab bot "merespons sendiri").
 */
const SEEN_FILE = path.join(DATA_DIR, '.seen-ids.json');

/** Parse string cookie sederhana (tanpa dependensi tambahan). */
function parseCookies(header) {
  const out = {};
  if (!header) return out;
  for (const part of header.split(';')) {
    const eq = part.indexOf('=');
    if (eq === -1) continue;
    out[part.slice(0, eq).trim()] = decodeURIComponent(part.slice(eq + 1).trim());
  }
  return out;
}

/** Apakah request ini punya akses ke /qr (/qr.png)? */
function qrAllowed(req) {
  if (!QR_PASSWORD) return true; // proteksi nonaktif
  if (req.query && req.query.token === QR_PASSWORD) return true; // via URL ?token=
  const cookies = parseCookies(req.headers.cookie);
  return cookies[QR_COOKIE] === '1';
}

/** Halaman login kecil untuk /qr (tema gelap seperti dashboard). */
function qrLoginPage(showError) {
  const err = showError
    ? '<div class="err">⛔ Password salah. Coba lagi.</div>'
    : '';
  return `<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QR Terkunci — Sales Canvas</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0b141a; color: #e9edef; min-height: 100vh; display: grid; place-items: center; padding: 24px; }
  .card { width: min(360px, 100%); background: #111b21; border: 1px solid #263055; border-radius: 16px; padding: 30px; text-align: center; }
  .logo { font-size: 40px; margin-bottom: 12px; }
  h1 { font-size: 18px; margin-bottom: 6px; }
  p { color: #8696a0; font-size: 13px; margin-bottom: 20px; }
  input { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid #263055; background: #0b141a; color: #e9edef; font-size: 14px; outline: none; }
  input:focus { border-color: #00a884; }
  button { width: 100%; margin-top: 14px; padding: 12px; border: 0; border-radius: 10px; background: #00a884; color: #fff; font-size: 14px; font-weight: 700; cursor: pointer; }
  .err { margin-top: 14px; padding: 10px; border-radius: 8px; font-size: 13px; background: rgba(248,113,113,.12); border: 1px solid rgba(248,113,113,.4); color: #f87171; }
</style>
</head>
<body>
  <form class="card" method="post" action="/qrlogin">
    <div class="logo">🔐</div>
    <h1>QR WhatsApp Terkunci</h1>
    <p>Masukkan password untuk melihat QR Code.</p>
    <input type="password" name="password" placeholder="Password" autofocus required />
    ${err}
    <button type="submit">Masuk</button>
  </form>
</body>
</html>`;
}

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

/** Teks menu bernomor (bekerja di Web, Desktop, dan HP). */
function menuText() {
  return [
    '🤖 Sales Canvas Bot',
    '',
    '📱 Di HP: ketuk tombol di bawah.',
    '💻 Di WhatsApp Web/Desktop: ketik angka di bawah ini:',
    '',
    ...MENU.map((b, i) => `${i + 1}. ${b.label}`),
    '',
    'Atau kirim foto struk untuk mencatat penjualan.',
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
  await sendText(sock, jid, menuText());
  // 2) tombol interaktif
  // Catatan: sendMessage() tidak mengenali interactiveMessage di Baileys 6.7.x
  // (jatuh ke prepareWAMessageMedia -> "Invalid media type"). Solusi yang benar:
  // bangun pesan via generateWAMessageFromContent lalu kirim via relayMessage().
  try {
    const msg = generateWAMessageFromContent(
      jid,
      {
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
      },
      { userJid: sock.user?.id }
    );
    await sock.relayMessage(jid, msg.message, { messageId: msg.key.id });
    rememberSentId(msg.key.id);
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
  if (data && data.reply) await sendText(sock, jid, data.reply);
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
  if (data && data.reply) await sendText(sock, sender, data.reply);
}

// ---------------------------------------------------------------------------
// Endpoint kecil untuk mengirim pesan dari Python (fitur proaktif)
// ---------------------------------------------------------------------------

let sockRef = null;
let connected = false; // true jika sudah tertaut (QR tidak berlaku lagi)

// Id pesan yang bridge sendiri kirim (sesi ini) — dipakai untuk membedakan
// pesan dari perangkat lain akun yang sama (chat ke diri sendiri, fromMe=true)
// dari pesan yang bridge buat sendiri.
const sentMessageIds = new Set();
const SENT_IDS_MAX = 2000;

function rememberSentId(id) {
  if (!id) return;
  sentMessageIds.add(id);
  if (sentMessageIds.size > SENT_IDS_MAX) {
    sentMessageIds.delete(sentMessageIds.values().next().value);
  }
  // id balasan juga masuk ke set persisten -> tidak akan diproses lagi
  rememberProcessedId(id);
}

// ---------------------------------------------------------------------------
// Dedup & persist id pesan yang sudah ditangani
// ---------------------------------------------------------------------------

// Semua id pesan yang sudah pernah bridge tangani (kirim ATAU proses), tersimpan
// ke file agar bertahan antar-restart.
let seenMessageIds = new Set();
const SEEN_IDS_MAX = 50000;
let seenSaveTimer = null;

function loadSeenIds() {
  try {
    const arr = JSON.parse(fs.readFileSync(SEEN_FILE, 'utf8'));
    if (Array.isArray(arr)) {
      seenMessageIds = new Set(arr);
      console.log(`[bridge] dimuat ${seenMessageIds.size} id pesan tersimpan`);
    }
  } catch (_) {
    /* file belum ada — set tetap kosong */
  }
}

function saveSeenIds() {
  clearTimeout(seenSaveTimer);
  seenSaveTimer = setTimeout(() => {
    try {
      fs.writeFileSync(SEEN_FILE, JSON.stringify([...seenMessageIds]));
    } catch (e) {
      console.error('[bridge] gagal simpan id pesan:', e.message);
    }
  }, 3000);
}

function rememberProcessedId(id) {
  if (!id) return;
  seenMessageIds.add(id);
  if (seenMessageIds.size > SEEN_IDS_MAX) {
    // buang id tertua agar tidak membengkak tanpa batas
    seenMessageIds.delete(seenMessageIds.values().next().value);
  }
  saveSeenIds();
}

/** Apakah timestamp pesan masih baru (dalam N detik dari sekarang)? */
function isRecent(ts, maxAgeSec = 600) {
  if (!ts) return false;
  // timestamp bisa berupa angka (unix), string angka, atau tanggal ISO
  const num = Number(ts);
  const t = Number.isFinite(num) ? num : Date.parse(ts) / 1000;
  if (Number.isNaN(t)) return false;
  return Date.now() / 1000 - t < maxAgeSec;
}

/** Kirim teks sambil mencatat id-nya (agar tidak diproses sebagai pesan masuk). */
async function sendText(sock, jid, text) {
  const sent = await sock.sendMessage(jid, { text });
  rememberSentId(sent && sent.key && sent.key.id);
  return sent;
}

/** Endpoint kecil agar Python bisa mengirim pesan ke WhatsApp (fitur proaktif). */
function startExpress() {
  const app = express();
  app.use(express.json());
  // untuk form login /qrlogin (password)
  app.use(express.urlencoded({ extended: false }));
  app.post('/send', async (req, res) => {
    const { to, text } = req.body || {};
    if (req.headers['x-secret'] !== SECRET) return res.status(401).json({ ok: false });
    if (!sockRef || !to || !text) return res.status(400).json({ ok: false });
    try {
      const sent = await sockRef.sendMessage(to, { text });
      rememberSentId(sent && sent.key && sent.key.id);
      res.json({ ok: true });
    } catch (e) {
      res.status(500).json({ ok: false, error: String(e) });
    }
  });
  // Kelola whitelist nomor WhatsApp dari Python (perintah bot).
  // Body JSON: { action: 'add'|'remove'|'list', number?: '628xxxx' }
  app.post('/admin/whitelist', (req, res) => {
    if (req.headers['x-secret'] !== SECRET) return res.status(401).json({ ok: false });
    const { action, number } = req.body || {};
    if (action === 'add') return res.json(waWhitelistAdd(number));
    if (action === 'remove') return res.json(waWhitelistRemove(number));
    if (action === 'list') return res.json(waWhitelistList());
    return res.status(400).json({ ok: false, error: 'action harus add | remove | list' });
  });
  app.get('/health', (req, res) => res.json({ ok: !!sockRef }));

  // QR sebagai gambar: /qr.png (PNG mentah) dan /qr (halaman dengan auto-refresh)
  app.post('/qrlogin', (req, res) => {
    const pw = (req.body && req.body.password) || '';
    if (!QR_PASSWORD || pw !== QR_PASSWORD) {
      return res.type('html').send(qrLoginPage(true));
    }
    res.setHeader(
      'Set-Cookie',
      `${QR_COOKIE}=1; Path=/; HttpOnly; SameSite=Lax; Max-Age=${Math.floor(QR_COOKIE_MAXAGE / 1000)}`
    );
    res.redirect('/qr');
  });
  app.get('/qr.png', (req, res) => {
    if (!qrAllowed(req)) {
      return res.status(403).type('text/plain').send('Forbidden — butuh password (lihat /qr).');
    }
    if (!fs.existsSync(QR_PNG)) {
      return res.status(404).type('text/plain').send('QR belum tersedia — tunggu beberapa detik.');
    }
    res.sendFile(QR_PNG);
  });
  app.get('/qr', (req, res) => {
    if (!qrAllowed(req)) {
      return res.type('html').send(qrLoginPage(false));
    }
    // Status khusus: sudah tertaut -> QR tidak diperlukan lagi
    let content;
    if (connected) {
      content = `
  <h1>✅ WhatsApp Terhubung</h1>
  <p>Bot sudah tertaut ke WhatsApp Anda — <b>tidak perlu scan QR lagi</b>.<br>Kirim <b>foto struk</b> atau ketik <b>menu</b> di chat WhatsApp untuk mencoba.</p>
  <div class="badge" style="background:#22c55e">Status: terhubung</div>`;
    } else if (!fs.existsSync(QR_PNG)) {
      content = `
  <h1>📲 Menunggu QR…</h1>
  <p>QR belum tersedia. Halaman ini otomatis memuat ulang — tunggu beberapa detik.</p>
  <div class="badge">Menyiapkan QR…</div>`;
    } else {
      content = `
  <h1>📲 Scan QR WhatsApp</h1>
  <p>Buka <b>WhatsApp → Pengaturan → Perangkat tertaut</b> lalu scan gambar di bawah ini.<br>Halaman ini otomatis memuat ulang QR setiap beberapa detik.</p>
  <img id="qr" src="/qr.png" alt="QR Code">
  <div class="badge">Menunggu scan…</div>
<script>
  const img = document.getElementById('qr');
  function refresh() { img.src = '/qr.png?t=' + Date.now(); }
  setInterval(refresh, 4000);
</script>`;
    }
    const html = `<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scan QR — Sales Canvas Bot</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0b141a; color: #e9edef; display: flex; flex-direction: column; align-items: center; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 6px; }
  p { color: #8696a0; margin: 4px 0 20px; text-align: center; max-width: 420px; line-height: 1.5; }
  img { width: min(320px, 80vw); height: auto; border-radius: 12px; background: #fff; padding: 8px; box-shadow: 0 8px 30px rgba(0,0,0,.5); }
  .badge { background: #00a884; color: #fff; padding: 6px 14px; border-radius: 999px; font-size: 13px; margin-top: 18px; }
</style>
</head>
<body>
${content}
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
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
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
      connected = true;
      fs.rmSync(QR_PNG, { force: true });
      console.log('[bridge] ✅ WhatsApp terhubung! Kirim foto struk, atau ketik "menu" untuk tombol perintah.');
    }
    // saat koneksi tertutup / logout, QR mungkin diperlukan lagi
    if (connection === 'close') {
      connected = false;
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const msg of messages) {
      const sender = msg.key.remoteJid;
      const msgId = msg.key.id;

      // 1) sudah pernah ditangani (dikirim/diproses, termasuk sesi sebelumnya)
      if (seenMessageIds.has(msgId)) {
        console.log('[bridge] diabaikan (sudah diproses):', msgId);
        continue;
      }
      // 2) pesan yang bridge sendiri kirim sesi ini
      if (msg.key.fromMe && sentMessageIds.has(msgId)) {
        console.log('[bridge] diabaikan (balasan sendiri):', msgId);
        continue;
      }
      // 3) pesan dari perangkat lain akun yang sama (chat ke diri sendiri dari
      //    HP) — HANYA diproses bila BARU. Pesan lama yang di-deliver ulang
      //    setelah reconnect/restart (umur > 10 menit) diabaikan, ini penyebab
      //    utama bot "merespons sendiri".
      if (msg.key.fromMe && !isRecent(msg.messageTimestamp, 600)) {
        console.log('[bridge] diabaikan (pesan sendiri lama, umur > 10m):', msgId);
        continue;
      }
      if (!msg.message) {
        console.log('[bridge] diabaikan (tanpa isi):', sender || '(no jid)');
        continue;
      }
      // hanya chat 1:1 — abaikan status broadcast & grup
      // (jangan whitelist suffix @s.whatsapp.net: akun LID bisa memakai @lid)
      if (!sender || sender === 'status@broadcast' || sender.includes('@g.us')) continue;

      const content = unwrapEphemeral(msg.message);
      if (!content) continue;

      // Whitelist: pesan dari nomor LAIN (bukan perangkat sendiri) hanya
      // diproses bila nomornya terdaftar di WHATSAPP_ALLOWED_NUMBERS.
      if (!msg.key.fromMe && !isAllowedSender(sender)) {
        // tampilkan nomor ternormalisasi: untuk akun LID (mis. 1234567890@lid)
        // yang tercetak bukan nomor telepon — pemilik perlu tahu angka yang
        // harus ditambahkan ke whitelist
        console.log(
          '[bridge] ⛔ ditolak (nomor tidak terdaftar):',
          sender,
          '-> angka terdeteksi:',
          numberFromJid(sender)
        );
        try {
          await sendText(
            sock,
            sender,
            '⛔ Nomor WhatsApp Anda tidak terdaftar untuk memakai bot ini.\n' +
              'Hubungi pemilik bot untuk mengaktifkan akses.'
          );
        } catch (_) {
          /* abaikan */
        }
        // tandai agar tidak diproses ulang bila di-deliver ulang
        rememberProcessedId(msgId);
        continue;
      }

      // tandai sudah diproses SEBELUM await (duplikat langsung dilewati)
      rememberProcessedId(msgId);

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

        const ageMin = Math.round((Date.now() / 1000 - (Number(msg.messageTimestamp) || Date.now() / 1000)) / 60);
        console.log('[bridge] 💬 teks diterima dari', sender, `(fromMe=${msg.key.fromMe}, umur=${ageMin}m):`, textMsg.trim());
        await forwardText(sock, sender, textMsg.trim());
      } catch (e) {
        console.error('[bridge] error memproses pesan dari', sender, ':', e);
        try {
          await sendText(sock, sender, '⚠️ Terjadi kesalahan saat memproses pesan. Coba lagi.');
        } catch (_) {
          /* abaikan */
        }
      }
    }
  });
}

if (require.main === module) {
  loadSeenIds();
  startExpress();
  start().catch((e) => console.error('[bridge] fatal:', e));
}

module.exports = {
  MENU,
  NUM_TO_CMD,
  menuText,
  unwrapEphemeral,
  getButtonId,
  sendMenu,
  isRecent,
  numberFromJid,
  isAllowedSender,
  normalizeNumber,
  waWhitelistAdd,
  waWhitelistRemove,
  waWhitelistList,
  validPhoneNumber,
};
