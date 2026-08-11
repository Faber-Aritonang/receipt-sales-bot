/**
 * Unit test logika whitelist WhatsApp (whatsapp-bridge/index.js).
 *
 * Menjalankan:  node scripts/test_whitelist.js
 * (tanpa koneksi WhatsApp — hanya fungsi murni yang diuji)
 */
'use strict';

const path = require('path');
const os = require('os');
const fs = require('fs');

// file whitelist sementara agar test tidak menyentuh file asli
const TMP_FILE = path.join(os.tmpdir(), `whitelist-test-${process.pid}.json`);
process.env.WHATSAPP_ALLOW_LIST_FILE = TMP_FILE;
process.env.WHATSAPP_ALLOWED_NUMBERS = '';

const bridge = require('../whatsapp-bridge/index.js');

let passed = 0;
let failed = 0;

function assert(cond, label) {
  if (cond) {
    passed++;
    console.log(`  ✅ ${label}`);
  } else {
    failed++;
    console.log(`  ❌ ${label}`);
  }
}

function reset() {
  try {
    fs.rmSync(TMP_FILE, { force: true });
  } catch (_) {
    /* abaikan */
  }
  // muat ulang modul dengan state bersih
  delete require.cache[require.resolve('../whatsapp-bridge/index.js')];
  process.env.WHATSAPP_ALLOW_LIST_FILE = TMP_FILE;
  process.env.WHATSAPP_ALLOWED_NUMBERS = '';
  const m = require('../whatsapp-bridge/index.js');
  return m;
}

// ---------------------------------------------------------------- normalize
console.log('\n── normalizeNumber & numberFromJid ──');
{
  const m = reset();
  assert(m.normalizeNumber('+62 812-3456-789') === '628123456789', 'strip + spasi - (normalisasi)');
  assert(m.normalizeNumber('628123') === '628123', 'angka polos tetap');
  assert(m.normalizeNumber('') === '', 'kosong -> kosong');
  assert(m.numberFromJid('628123456789@s.whatsapp.net') === '628123456789', 'JID s.whatsapp.net');
  assert(m.numberFromJid('177798912163960@lid') === '177798912163960', 'JID @lid');
}

// ---------------------------------------------------------------- env sebagai nilai awal
console.log('\n── nilai awal dari env ──');
{
  // buang file sisa dari blok sebelumnya agar test tidak bergantung pada urutan
  try {
    fs.rmSync(TMP_FILE, { force: true });
  } catch (_) {
    /* abaikan */
  }
  delete require.cache[require.resolve('../whatsapp-bridge/index.js')];
  process.env.WHATSAPP_ALLOW_LIST_FILE = TMP_FILE;
  process.env.WHATSAPP_ALLOWED_NUMBERS = '628123456789, +62 811-0000-1111';
  const m = require('../whatsapp-bridge/index.js');
  const l = m.waWhitelistList();
  assert(l.allowed.includes('628123456789'), 'nomor 1 dari env');
  assert(l.allowed.includes('6281100001111'), 'nomor 2 dari env (ternormalisasi)');
}

// ---------------------------------------------------------------- add / remove / list
console.log('\n── add / remove / list (file persisten) ──');
{
  const m = reset();
  m.waWhitelistAdd('628123456789');
  const a = m.waWhitelistAdd('6281111111111');
  assert(a.ok && a.allowed.includes('6281111111111'), 'add nomor baru');
  assert(fs.existsSync(TMP_FILE), 'file whitelist tersimpan ke disk');
  const r = m.waWhitelistRemove('628123456789');
  assert(r.ok && !r.allowed.includes('628123456789'), 'remove nomor');
  assert(m.waWhitelistList().allowed.includes('6281111111111'), 'nomor lain tetap ada');
}

// ---------------------------------------------------------------- blokir nomor tak terdaftar
console.log('\n── blokir nomor yang tidak ada di daftar ──');
{
  const m = reset();
  m.waWhitelistAdd('6281111111111');
  const r = m.waWhitelistRemove('6289999999999');
  assert(r.ok === false, 'blokir nomor tak terdaftar DITOLAK');
  assert(/tidak ada di daftar/.test(r.error), 'pesan error: nomor tidak ada di daftar');
}

// ---------------------------------------------------------------- validasi format nomor
console.log('\n── validasi format nomor ──');
{
  const m = reset();
  assert(m.validPhoneNumber('628123456789') === true, 'nomor 12 digit valid');
  assert(m.validPhoneNumber('1234567') === false, 'terlalu pendek (<8) ditolak');
  assert(m.validPhoneNumber('1234567890123456') === false, 'terlalu panjang (>15) ditolak');
  const bad = m.waWhitelistAdd('123');
  assert(bad.ok === false, 'add nomor pendek ditolak');
  const good = m.waWhitelistAdd('628123456789');
  assert(good.ok === true, 'add nomor valid diterima');
}

// ---------------------------------------------------------------- guard nomor terakhir
console.log('\n── guard: tidak bisa hapus nomor terakhir ──');
{
  const m = reset();
  m.waWhitelistAdd('628123456789');
  const r = m.waWhitelistRemove('628123456789');
  assert(r.ok === false, 'remove nomor terakhir DITOLAK');
  assert(/terakhir/.test(r.error), 'pesan error menyebut nomor terakhir');
  assert(m.waWhitelistList().allowed.includes('628123456789'), 'nomor tetap ada setelah ditolak');
}

// ---------------------------------------------------------------- isAllowedSender
console.log('\n── isAllowedSender ──');
{
  const m = reset();
  m.waWhitelistAdd('628123456789');
  assert(m.isAllowedSender('628123456789@s.whatsapp.net') === true, 'nomor terdaftar -> boleh');
  assert(m.isAllowedSender('6289999999999@s.whatsapp.net') === false, 'nomor asing -> ditolak');
  assert(m.isAllowedSender(null) === false, 'jid kosong -> ditolak');
}

console.log('\n── mode terbuka (whitelist kosong) ──');
{
  const m = reset(); // tanpa add apa pun -> set kosong
  assert(m.isAllowedSender('6289999999999@s.whatsapp.net') === true, 'set kosong -> semua boleh');
}

// ---------------------------------------------------------------- pembersihan
try {
  fs.rmSync(TMP_FILE, { force: true });
} catch (_) {
  /* abaikan */
}

console.log(`\nHASIL: ${passed} lolos, ${failed} gagal\n`);
process.exit(failed ? 1 : 0);
