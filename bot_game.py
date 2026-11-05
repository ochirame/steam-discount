"""Bot game GRATIS + DISKON (Steam & Epic) dalam SATU file, kirim ke webhook Discord.

Jalankan:
    python bot_game.py              # jalan terus (gratis + diskon), auto-reconnect
    python bot_game.py --sekali     # cek sekali lalu selesai
    python bot_game.py --tes        # tes webhook
    python bot_game.py --gratis     # hanya bagian gratis   (bisa digabung dengan opsi lain)
    python bot_game.py --diskon     # hanya bagian diskon

.env (satu folder dengan file ini):
    WEBHOOK_GRATIS=...   ROLE_ID_GRATIS=...
    WEBHOOK_DISKON=...   ROLE_ID_DISKON=...
    ITAD_KEY=...         (opsional)
    (WEBHOOK / ROLE_ID biasa dipakai sebagai cadangan kalau yang spesifik kosong)
"""
import html, json, os, re, socket, sys, time
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    p = os.path.join(BASE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


load_env()

WEBHOOK_GRATIS = (os.environ.get("WEBHOOK_GRATIS") or os.environ.get("WEBHOOK", "")).strip()
ROLE_GRATIS = (os.environ.get("ROLE_ID_GRATIS") or os.environ.get("ROLE_ID", "")).strip()
WEBHOOK_DISKON = (os.environ.get("WEBHOOK_DISKON") or os.environ.get("WEBHOOK", "")).strip()
ROLE_DISKON = (os.environ.get("ROLE_ID_DISKON") or os.environ.get("ROLE_ID", "")).strip()
ITAD_KEY = os.environ.get("ITAD_KEY", "").strip()  # API key IsThereAnyDeal (opsional)

# =====================================================================
#                          PENGATURAN
# =====================================================================
# ---------- umum ----------
INTERVAL_MENIT = 30
CC, LANG = "id", "indonesian"
HANYA_GAME = True           # skip DLC, soundtrack, software
BLACKLIST_KATA = ["hentai", "waifu", "nsfw", "uncensored", "sex"]
BLACKLIST_GENRE = ["sexual content", "nudity"]
BLOKIR_18PLUS = True        # skip game berlabel konten dewasa di Steam
WHITELIST_KATA = []         # contoh: ["hades", "elden ring", "stardew"]

# ---------- bagian GRATIS ----------
G_CEK_EPIC = True
G_CEK_STEAM = True
GRATIS_AKAN = True          # kabari juga game Epic yang SEGERA gratis
G_MAKS_HALAMAN_STEAM = 3    # Steam: 50 game per halaman
G_PER_PESAN = 5
G_SIMPAN_HARI = 30          # lama game dianggap sudah dikirim
G_TOLAK_JAM = 12            # game yang tidak lolos dicek ulang setelah sekian jam
# Steam murah (selain yang gratis)
STEAM_MURAH = True          # kirim juga game Steam diskon besar / harga murah
DISKON_BESAR = 90           # diskon >= ini (%) ikut dikirim
HARGA_MURAH = 50_000        # harga setelah diskon <= ini (Rupiah) ikut dikirim
G_MIN_ULASAN_PERSEN = 0     # game murah ditolak kalau ulasan positif di bawah ini
G_MIN_ULASAN_CEK = 200000   # persen ulasan baru dinilai kalau ulasan >= ini
MAKS_CEK_DETAIL = 60        # maks game Steam yang dicek detailnya per siklus

# ---------- bagian DISKON ----------
D_CEK_STEAM = True
D_CEK_EPIC = False          # Steam saja (ubah ke True kalau mau Epic lagi)
MIN_DISKON = 20             # minimal diskon (%)
MIN_HARGA = 75_000          # harga min setelah diskon (Rupiah), 0 = bebas
MAKS_HARGA = 1_000_000      # harga maks setelah diskon (Rupiah), 0 = bebas
MIN_DISKON_WL = 20          # diskon minimal untuk game whitelist
# Popularitas dari jumlah ulasan Steam:
#   >= 10.000 Sangat populer | >= 1.000 Populer | >= 100 Cukup populer | sisanya Non populer
TAMPILKAN_NON_POPULER = True  # False = kirim hanya game yang minimal "Cukup populer"
D_MIN_ULASAN_PERSEN = 0     # minimal % ulasan positif (dicek kalau ulasan >= D_MIN_ULASAN_CEK)
D_MIN_ULASAN_CEK = 20000    # di bawah ini persen ulasan dianggap belum bisa dinilai
MIN_METACRITIC = 0          # 0 = nonaktif
EPIC_TANPA_ULASAN_LOLOS = True  # game Epic yang tidak ketemu di Steam tetap dikirim
PING_DISKON = 80            # diskon >= ini akan ping role (harga terendah juga)
D_MAKS_HALAMAN = 10         # Steam: 50 game per halaman
MAKS_HALAMAN_EPIC = 5       # Epic: 40 game per halaman
MAKS_BARU = 30              # maksimal game dikirim per siklus
D_PER_PESAN = 5
D_SIMPAN_HARI = 14          # lama game dianggap sudah dikirim
D_TOLAK_JAM = 12            # game yang ditolak filter dicek ulang setelah sekian jam
# =====================================================================

G_SEEN_FILE = "seen_gratis.json"
G_TTL = {"free": G_SIMPAN_HARI * 86400, "tolak": G_TOLAK_JAM * 3600}
D_SEEN_FILE = "seen_diskon.json"
D_TTL = {"games": D_SIMPAN_HARI * 86400, "steam": D_SIMPAN_HARI * 86400, "tolak": D_TOLAK_JAM * 3600}

S = requests.Session()
S.headers["User-Agent"] = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                           "Chrome/120 Mobile Safari/537.36")
# retry otomatis untuk GET kalau koneksi putus sebentar / server error sementara
_retry = Retry(total=3, connect=3, read=2, backoff_factor=1.5,
               status_forcelist=(500, 502, 503, 504), allowed_methods=["GET"])
S.mount("https://", HTTPAdapter(max_retries=_retry))
S.mount("http://", HTTPAdapter(max_retries=_retry))


# =====================================================================
#                          FUNGSI UMUM
# =====================================================================
def log(*a):
    print(datetime.now().strftime("[%H:%M:%S]"), *a, flush=True)


def rupiah(n):
    return "Rp" + f"{n:,.0f}".replace(",", ".")


def potong(teks, n):
    teks = html.unescape(teks or "").strip()
    return teks if len(teks) <= n else teks[: n - 1].rstrip() + "…"


def norm(judul):
    t = html.unescape(judul or "").lower().replace("&", "and")
    t = re.sub(r"[™®©]", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def ts(s):
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def wl(nama):
    n = (nama or "").lower()
    return any(k.lower() in n for k in WHITELIST_KATA)


def diblokir(nama, d=None):
    if wl(nama):
        return False
    n = (nama or "").lower()
    if any(k.lower() in n for k in BLACKLIST_KATA):
        return True
    if d:
        if BLOKIR_18PLUS and set((d.get("content_descriptors") or {}).get("ids", [])) & {3, 4}:
            return True
        gen = {x["description"].lower() for x in d.get("genres", [])}
        if gen & set(BLACKLIST_GENRE):
            return True
    return False


def popularitas(rv):
    """Kelompok popularitas dari jumlah ulasan Steam."""
    if not rv:
        return "Belum ada ulasan"
    t = rv["total"]
    if t >= 10000:
        return "Sangat populer"
    if t >= 1000:
        return "Populer"
    if t >= 100:
        return "Cukup populer"
    return "Non populer"


def teks_ulasan(rv):
    if rv:
        return (f'{rv["desc"]} ({rv["persen"]}% dari {rv["total"]:,} ulasan)'
                .replace(",", ".") + f' • **{popularitas(rv)}**')
    return "Belum ada ulasan • **Non populer**"


# ================== KONEKSI INTERNET ==================
class TidakAdaInternet(Exception):
    """Dilempar saat internet putus di tengah siklus; siklus diulang setelah nyambung lagi."""


def ada_internet():
    """Cek koneksi langsung ke IP publik (tanpa DNS) supaya cepat dan akurat."""
    for host in (("1.1.1.1", 443), ("8.8.8.8", 443)):
        try:
            socket.create_connection(host, timeout=5).close()
            return True
        except OSError:
            continue
    return False


def tunggu_internet():
    """Blok sampai internet ada lagi. Cek makin jarang (10s -> maks 60s) biar hemat baterai."""
    if ada_internet():
        return
    mulai, jeda = time.time(), 10
    log("Internet putus, menunggu koneksi kembali...")
    while not ada_internet():
        time.sleep(jeda)
        jeda = min(jeda * 2, 60)
    log(f"Internet nyambung lagi (putus ±{int((time.time() - mulai) // 60)} menit).")
    time.sleep(3)  # kasih waktu koneksi/DNS stabil dulu


def jalankan_terus(siklus, interval_menit):
    """Loop utama: tidak pernah berhenti, otomatis lanjut setelah internet balik."""
    while True:
        tunggu_internet()
        try:
            siklus()
        except TidakAdaInternet:
            log("Internet putus di tengah siklus, diulang setelah nyambung lagi.")
            continue
        except Exception as e:
            log("Error siklus:", repr(e))
            if not ada_internet():
                continue
        time.sleep(interval_menit * 60)


# ================== PENYIMPANAN ==================
def load_seen(nama_file, ttl):
    """ttl: {nama_bagian: detik}. Tiap bagian pakai file seen sendiri."""
    path = os.path.join(BASE, nama_file)
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    now = time.time()
    seen = {}
    for k, detik in ttl.items():
        seen[k] = {}
        for a, b in (data.get(k) or {}).items():
            t = b.get("t", 0) if isinstance(b, dict) else b
            if t > now - detik:
                seen[k][a] = b
    seen["gagal"] = data.get("gagal") or {}
    return seen


def save_seen(nama_file, seen):
    """Tulis atomik: kalau HP mati/Termux ditutup saat nulis, file lama tidak rusak."""
    path = os.path.join(BASE, nama_file)
    with open(path + ".tmp", "w") as f:
        json.dump(seen, f)
    os.replace(path + ".tmp", path)


# ================== DISCORD ==================
def kirim_payload(webhook, payload):
    for _ in range(3):
        try:
            res = requests.post(webhook, json=payload, timeout=20)
            if res.status_code == 429:
                tunggu = res.json().get("retry_after", 5)
                log(f"Rate limit Discord, tunggu {tunggu}s")
                time.sleep(float(tunggu) + 0.5)
                continue
            ok = res.status_code in (200, 204)
            log("Discord:", res.status_code, "" if ok else res.text[:200])
            return ok
        except (requests.RequestException, ValueError) as e:
            log("Kirim ke Discord gagal:", repr(e))
            time.sleep(3)
    return False


def kirim(webhook, embeds, header=None, role_id="", ping=False):
    content = header or ""
    payload = {"embeds": embeds}
    if ping and role_id:
        content = f"<@&{role_id}> {content}".strip()
        payload["allowed_mentions"] = {"roles": [role_id]}
    payload["content"] = content or None
    return kirim_payload(webhook, payload)


def kirim_teks(webhook, teks):
    return kirim_payload(webhook, {"content": teks})


def catat(webhook, seen, toko, ok):
    if not ok and not ada_internet():
        raise TidakAdaInternet()   # gagal karena offline: jangan dihitung, ulang nanti
    g = seen["gagal"]
    sebelum = g.get(toko, 0)
    g[toko] = 0 if ok else sebelum + 1
    if not ok and g[toko] == 3:
        kirim_teks(webhook, f"⚠️ **{toko}** gagal dicek 3 siklus berturut-turut. Cek log bot di Termux.")
    if ok and sebelum >= 3:
        kirim_teks(webhook, f"✅ **{toko}** sudah normal lagi.")


# ================== STEAM ==================
def steam_specials():
    hasil = {}
    r = S.get("https://store.steampowered.com/api/featuredcategories",
              params={"cc": CC, "l": LANG}, timeout=20)
    for g in r.json().get("specials", {}).get("items", []):
        if g.get("id"):
            hasil[int(g["id"])] = g.get("discount_percent", 0)
    return hasil


def steam_pencarian(maks_halaman, extra=None):
    hasil = {}
    for hal in range(maks_halaman):
        params = {"query": "", "start": hal * 50, "count": 50, "specials": 1,
                  "infinite": 1, "cc": CC, "l": LANG}
        if HANYA_GAME:
            params["category1"] = 998
        params.update(extra or {})
        r = S.get("https://store.steampowered.com/search/results/", params=params, timeout=20)
        data = r.json()
        h = data.get("results_html", "")
        ketemu = 0
        for m in re.finditer(r'<a [^>]*?data-ds-appid="(\d+)"[^>]*>(.*?)</a>', h, re.S):
            d = re.search(r'data-discount="(\d+)"', m.group(2))
            hasil[int(m.group(1))] = int(d.group(1)) if d else 0
            ketemu += 1
        if ketemu == 0 or (hal + 1) * 50 >= data.get("total_count", 0):
            break
        time.sleep(1)
    return hasil


def steam_kandidat(maks_halaman, extra=None):
    """Gabungan specials + pencarian. Error hanya kalau KEDUA sumber gagal."""
    kandidat, gagal = {}, 0
    sumber = (("specials", steam_specials),
              ("pencarian", lambda: steam_pencarian(maks_halaman, extra)))
    for nama, fn in sumber:
        try:
            hasil = fn()
            log(f"Steam {nama}: {len(hasil)} game")
            for k, v in hasil.items():
                kandidat[k] = max(v, kandidat.get(k, 0))
        except Exception as e:
            gagal += 1
            log(f"Steam {nama} gagal: {e}")
    if gagal == len(sumber):
        raise RuntimeError("Steam tidak mengembalikan data")
    return kandidat


def steam_details(appid):
    try:
        r = S.get("https://store.steampowered.com/api/appdetails",
                  params={"appids": appid, "cc": CC, "l": LANG}, timeout=20)
        d = r.json()[str(appid)]
        return d["data"] if d.get("success") else None
    except Exception:
        return None


def steam_reviews(appid):
    try:
        r = S.get(f"https://store.steampowered.com/appreviews/{appid}",
                  params={"json": 1, "language": "all", "purchase_type": "all", "num_per_page": 0},
                  timeout=20)
        s = r.json().get("query_summary", {})
        total = s.get("total_reviews", 0)
        if not total:
            return None
        return {"persen": round(s["total_positive"] / total * 100), "total": total,
                "desc": s.get("review_score_desc", "-")}
    except Exception:
        return None


def steam_cari_appid(judul):
    """Cari appid Steam dari judul (dipakai buat ngecek ulasan game Epic)."""
    try:
        r = S.get("https://store.steampowered.com/api/storesearch/",
                  params={"term": judul, "cc": CC, "l": LANG}, timeout=20)
        for it in r.json().get("items", []):
            if norm(it.get("name")) == norm(judul):
                return it["id"]
    except Exception:
        pass
    return None


# ================== EPIC ==================
def epic_slug(el):
    for sumber in (el.get("offerMappings") or [], (el.get("catalogNs") or {}).get("mappings") or []):
        for m in sumber:
            if m.get("pageSlug"):
                return m["pageSlug"]
    slug = el.get("productSlug") or el.get("urlSlug")
    return slug.split("/")[0] if slug else None


def epic_gambar(el):
    for tipe in ("OfferImageWide", "DieselStoreFrontWide", "Thumbnail"):
        for k in el.get("keyImages") or []:
            if k.get("type") == tipe:
                return k["url"]
    return ""


def epic_harga(el):
    try:
        tp = el["price"]["totalPrice"]
        dec = (tp.get("currencyInfo") or {}).get("decimals", 2)
        return tp["originalPrice"] / 10 ** dec, tp["discountPrice"] / 10 ** dec
    except Exception:
        return None


# =====================================================================
#                      BAGIAN 1: GAME GRATIS
# =====================================================================
def epic_gratis(seen):
    """Game gratis Epic (sedang berlangsung & akan datang). Return (embeds, keys)."""
    r = S.get("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions",
              params={"locale": "id", "country": CC.upper(), "allowCountries": CC.upper()}, timeout=20)
    els = r.json()["data"]["Catalog"]["searchStore"]["elements"]
    embeds, keys = [], []
    for el in els:
        if "mystery" in (el.get("title") or "").lower():
            continue
        promos = el.get("promotions") or {}
        for jenis, label, warna in (("promotionalOffers", "🆓 GRATIS SEKARANG", 0x2ECC71),
                                    ("upcomingPromotionalOffers", "⏳ SEGERA GRATIS", 0xF1C40F)):
            if jenis.startswith("upcoming") and not GRATIS_AKAN:
                continue
            for blok in promos.get(jenis) or []:
                for po in blok.get("promotionalOffers") or []:
                    if (po.get("discountSetting") or {}).get("discountPercentage") != 0:
                        continue
                    key = f'{el["id"]}-{jenis[:2]}-{po.get("startDate")}'
                    if key in seen["free"]:
                        continue
                    slug = epic_slug(el)
                    url = f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/free-games"
                    h = epic_harga(el)
                    desc = f"**{label}**"
                    if h and h[0] > 0:
                        desc += f"\nNormal ~~{rupiah(h[0])}~~ → **Rp0**"
                    if el.get("description"):
                        desc += "\n\n" + potong(el["description"], 250)
                    fields = [{"name": "Toko", "value": "⬛ Epic Games", "inline": True}]
                    if (el.get("seller") or {}).get("name"):
                        fields.append({"name": "Publisher", "value": potong(el["seller"]["name"], 100), "inline": True})
                    a, b = ts(po.get("startDate", "")), ts(po.get("endDate", ""))
                    if a:
                        fields.append({"name": "Mulai", "value": f"<t:{a}:f> (<t:{a}:R>)", "inline": False})
                    if b:
                        fields.append({"name": "Berakhir", "value": f"<t:{b}:f> (<t:{b}:R>)", "inline": False})
                    embeds.append({
                        "title": el["title"], "url": url, "description": desc, "color": warna,
                        "fields": fields, "image": {"url": epic_gambar(el)},
                        "footer": {"text": "Epic Games • game gratis"},
                    })
                    keys.append(key)
    return embeds, keys


def embed_steam(appid, d, po, rv, gratis):
    nama = d.get("name", f"App {appid}")
    disc = po["discount_percent"]
    if gratis:
        desc = "**🆓 GRATIS SEKARANG**"
        if po["initial"] > 0:
            desc += f"\nNormal ~~{rupiah(po['initial'] / 100)}~~ → **Rp0**"
        warna, footer = 0x2ECC71, "Steam • game gratis"
    else:
        desc = f"**-{disc}%**  ~~{rupiah(po['initial'] / 100)}~~ → **{rupiah(po['final'] / 100)}**"
        warna, footer = 0x3498DB, "Steam • game murah"
    if d.get("short_description"):
        desc += "\n\n" + potong(d["short_description"], 250)
    fields = [{"name": "Toko", "value": "🟦 Steam", "inline": True}]
    if d.get("genres"):
        fields.append({"name": "Genre", "value": ", ".join(x["description"] for x in d["genres"][:4]), "inline": True})
    if d.get("developers"):
        fields.append({"name": "Developer", "value": potong(", ".join(d["developers"][:2]), 100), "inline": True})
    fields.append({"name": "Ulasan Steam", "value": teks_ulasan(rv), "inline": False})
    if gratis:
        fields.append({"name": "Catatan", "value": "Klaim sebelum promo habis (waktu berakhir tidak tersedia dari Steam).",
                       "inline": False})
    return {
        "title": nama, "url": f"https://store.steampowered.com/app/{appid}",
        "description": desc, "color": warna, "fields": fields,
        "image": {"url": d.get("header_image", "")}, "footer": {"text": footer},
    }


def steam_promo(seen):
    """Return (embed_gratis, key_gratis, embed_murah, key_murah)."""
    kandidat, gagal, percobaan = {}, 0, 0
    sumber = [{"maxprice": "free"}] + ([None] if STEAM_MURAH else [])
    for extra in sumber:
        percobaan += 1
        try:
            for k, v in steam_kandidat(G_MAKS_HALAMAN_STEAM, extra).items():
                kandidat[k] = max(v, kandidat.get(k, 0))
        except Exception as e:
            gagal += 1
            log("Steam kandidat gagal:", repr(e))
    if gagal == percobaan:
        raise RuntimeError("Steam tidak mengembalikan data")

    antrean = sorted((a for a, dsk in kandidat.items() if dsk > 0), key=lambda a: -kandidat[a])
    log(f"Steam kandidat: {len(antrean)}")
    g_emb, g_key, m_emb, m_key, dicek = [], [], [], [], 0
    for appid in antrean:
        dsk = kandidat[appid]
        k_awal = f"steam-{appid}-{dsk}"
        if k_awal in seen["free"] or k_awal in seen["tolak"]:
            continue
        if dicek >= MAKS_CEK_DETAIL:
            log(f"Batas {MAKS_CEK_DETAIL} cek detail tercapai, sisanya siklus berikutnya.")
            break
        dicek += 1
        d = steam_details(appid)
        time.sleep(1.2)
        po = (d or {}).get("price_overview")
        nama = (d or {}).get("name", "")
        if (not d or not po or (HANYA_GAME and d.get("type") != "game") or diblokir(nama, d)):
            seen["tolak"][k_awal] = time.time()
            continue

        disc = po["discount_percent"]
        harga = po["final"] / 100
        key = f"steam-{appid}-{disc}"
        if key in seen["free"]:
            continue
        gratis = po["final"] == 0 and disc >= 100
        murah = STEAM_MURAH and not gratis and (disc >= DISKON_BESAR or harga <= HARGA_MURAH)
        if not gratis and not murah:
            seen["tolak"][k_awal] = time.time()
            continue

        rv = steam_reviews(appid)
        time.sleep(1)
        if murah and rv and rv["total"] >= G_MIN_ULASAN_CEK and rv["persen"] < G_MIN_ULASAN_PERSEN:
            log(f"Ditolak: {nama} (ulasan {rv['persen']}% positif)")
            seen["tolak"][k_awal] = time.time()
            continue

        if gratis:
            g_emb.append(embed_steam(appid, d, po, rv, True)); g_key.append(key)
        else:
            m_emb.append(embed_steam(appid, d, po, rv, False)); m_key.append(key)
    return g_emb, g_key, m_emb, m_key


def kirim_batch_gratis(embeds, keys, seen, header, ping):
    now = time.time()
    for i in range(0, len(embeds), G_PER_PESAN):
        if kirim(WEBHOOK_GRATIS, embeds[i:i + G_PER_PESAN], header, role_id=ROLE_GRATIS, ping=ping):
            for k in keys[i:i + G_PER_PESAN]:
                seen["free"][k] = now
            save_seen(G_SEEN_FILE, seen)
        time.sleep(1)


def siklus_gratis():
    log("=== Mulai pengecekan game gratis ===")
    seen = load_seen(G_SEEN_FILE, G_TTL)

    if G_CEK_EPIC:
        try:
            embeds, keys = epic_gratis(seen)
            log(f"Epic gratis: {len(embeds)} baru")
            kirim_batch_gratis(embeds, keys, seen, "🆓 **Game gratis Epic Games!**", True)
            catat(WEBHOOK_GRATIS, seen, "Epic (gratis)", True)
        except Exception as e:
            log("Epic gratis gagal:", repr(e))
            catat(WEBHOOK_GRATIS, seen, "Epic (gratis)", False)

    if G_CEK_STEAM:
        try:
            g_emb, g_key, m_emb, m_key = steam_promo(seen)
            log(f"Steam gratis: {len(g_emb)} baru, murah: {len(m_emb)} baru")
            kirim_batch_gratis(g_emb, g_key, seen, "🆓 **Game gratis Steam!**", True)
            kirim_batch_gratis(m_emb, m_key, seen, "💸 **Game Steam murah!**", False)
            catat(WEBHOOK_GRATIS, seen, "Steam (gratis)", True)
        except Exception as e:
            log("Steam gratis gagal:", repr(e))
            catat(WEBHOOK_GRATIS, seen, "Steam (gratis)", False)

    save_seen(G_SEEN_FILE, seen)
    log("Selesai (gratis).")


# =====================================================================
#                      BAGIAN 2: DISKON GAME
# =====================================================================
def batas_diskon(nama):
    return MIN_DISKON_WL if wl(nama) else MIN_DISKON


def steam_offers(seen):
    kandidat = steam_kandidat(D_MAKS_HALAMAN)
    if not kandidat:
        raise RuntimeError("Steam tidak mengembalikan data")
    min_d = min(MIN_DISKON, MIN_DISKON_WL) if WHITELIST_KATA else MIN_DISKON
    antrean = [a for a, dsk in kandidat.items() if dsk == 0 or min_d <= dsk < 100]
    log(f"Steam kandidat setelah filter awal: {len(antrean)}")
    offers = []
    for appid in antrean:
        dsk = kandidat[appid]
        k_awal = f"steam-{appid}-{dsk}"
        if dsk and (k_awal in seen["steam"] or k_awal in seen["tolak"]):
            continue
        d = steam_details(appid)
        time.sleep(1.2)
        if not d:
            continue
        nama = d.get("name", f"App {appid}")
        po = d.get("price_overview")
        if (not po or po["discount_percent"] < batas_diskon(nama) or po["discount_percent"] >= 100
                or po["final"] <= 0
                or (MIN_HARGA and po["final"] / 100 < MIN_HARGA)
                or (HANYA_GAME and d.get("type") != "game") or diblokir(nama, d)):
            if dsk:
                seen["tolak"][k_awal] = time.time()
            continue
        offers.append({
            "store": "Steam", "id": appid, "name": nama,
            "price": po["final"] / 100, "orig": po["initial"] / 100,
            "disc": po["discount_percent"],
            "url": f"https://store.steampowered.com/app/{appid}",
            "key": f'steam-{appid}-{po["discount_percent"]}', "d": d,
        })
    return offers


EPIC_QUERY = """
query searchStoreQuery($allowCountries: String, $category: String, $count: Int, $country: String!,
  $locale: String, $sortBy: String, $sortDir: String, $start: Int, $onSale: Boolean) {
  Catalog {
    searchStore(allowCountries: $allowCountries, category: $category, count: $count,
      country: $country, locale: $locale, sortBy: $sortBy, sortDir: $sortDir,
      start: $start, onSale: $onSale) {
      elements {
        title id namespace description offerType productSlug urlSlug
        seller { name }
        keyImages { type url }
        catalogNs { mappings(pageType: "productHome") { pageSlug pageType } }
        offerMappings { pageSlug pageType }
        price(country: $country) {
          totalPrice { discountPrice originalPrice discount currencyInfo { decimals } }
        }
      }
      paging { count total }
    }
  }
}
"""


def epic_offers():
    offers, start, total = [], 0, 0
    for _ in range(MAKS_HALAMAN_EPIC):
        variables = {"allowCountries": CC.upper(), "country": CC.upper(), "locale": "id-ID",
                     "count": 40, "start": start, "onSale": True,
                     "sortBy": "title", "sortDir": "ASC"}
        if HANYA_GAME:
            variables["category"] = "games/edition/base"
        r = S.post("https://store.epicgames.com/graphql",
                   json={"query": EPIC_QUERY, "variables": variables},
                   headers={"Content-Type": "application/json", "Referer": "https://store.epicgames.com/"},
                   timeout=25)
        ss = r.json()["data"]["Catalog"]["searchStore"]
        elements = ss.get("elements") or []
        total = (ss.get("paging") or {}).get("total", 0)
        for el in elements:
            h = epic_harga(el)
            if not h:
                continue
            asli, akhir = h
            if asli <= 0 or akhir <= 0 or akhir >= asli:   # akhir <= 0 = gratis -> bagian gratis
                continue
            persen = round((asli - akhir) / asli * 100)
            if persen < batas_diskon(el["title"]) or persen >= 100 or diblokir(el["title"]):
                continue
            if HANYA_GAME and el.get("offerType") not in (None, "BASE_GAME"):
                continue
            slug = epic_slug(el)
            if not slug:
                continue
            offers.append({
                "store": "Epic", "id": el["id"], "name": el["title"],
                "price": akhir, "orig": asli, "disc": persen,
                "url": f"https://store.epicgames.com/p/{slug}",
                "key": f'epic-{el["id"]}-{persen}', "el": el, "image": epic_gambar(el),
            })
        start += 40
        if not elements or start >= total:
            break
        time.sleep(1)
    log(f"Epic: {len(offers)} game lolos filter diskon (dari {total} item on sale)")
    return offers


def itad_terendah(judul, harga):
    """True kalau harga sekarang <= harga terendah historis. None kalau tidak diketahui."""
    if not ITAD_KEY:
        return None
    try:
        r = S.get("https://api.isthereanydeal.com/games/lookup/v1",
                  params={"key": ITAD_KEY, "title": judul}, timeout=20)
        j = r.json()
        if not j.get("found"):
            return None
        gid = j["game"]["id"]
        r = S.post("https://api.isthereanydeal.com/games/historylow/v1",
                   params={"key": ITAD_KEY, "country": CC.upper()}, json=[gid], timeout=20)
        low = r.json()[0]["low"]
        price = low.get("price") or low
        if price.get("currency") not in (None, "IDR"):
            return None
        return harga <= float(price["amount"]) * 1.01
    except Exception as e:
        log("ITAD gagal:", repr(e))
        return None


def ambil_ulasan(o):
    appid = o["id"] if o["store"] == "Steam" else steam_cari_appid(o["name"])
    time.sleep(1)
    return steam_reviews(appid) if appid else None


def lolos_kualitas(o, rv):
    if wl(o["name"]):
        return True, "whitelist"
    if o["store"] == "Steam":
        meta = (o["d"].get("metacritic") or {}).get("score")
        if MIN_METACRITIC and meta and meta < MIN_METACRITIC:
            return False, f"metacritic {meta}"
    if not rv:
        if o["store"] == "Epic":
            return EPIC_TANPA_ULASAN_LOLOS, "tanpa data ulasan"
        return TAMPILKAN_NON_POPULER, "belum ada ulasan"
    if popularitas(rv) == "Non populer" and not TAMPILKAN_NON_POPULER:
        return False, f'non populer ({rv["total"]} ulasan)'
    if rv["total"] >= D_MIN_ULASAN_CEK and rv["persen"] < D_MIN_ULASAN_PERSEN:
        return False, f'ulasan {rv["persen"]}% positif'
    return True, "ok"


def buat_embed(o, lainnya, rv, low):
    desc = f'**-{o["disc"]}%**  ~~{rupiah(o["orig"])}~~ → **{rupiah(o["price"])}**'
    if low:
        desc += "\n🔥 **Harga terendah sepanjang masa!**"
    fields = [{"name": "Toko", "value": "🟦 Steam" if o["store"] == "Steam" else "⬛ Epic Games", "inline": True}]

    if o["store"] == "Steam":
        d = o["d"]
        if d.get("short_description"):
            desc += "\n\n" + potong(d["short_description"], 220)
        if d.get("genres"):
            fields.append({"name": "Genre", "value": ", ".join(x["description"] for x in d["genres"][:4]), "inline": True})
        if d.get("developers"):
            fields.append({"name": "Developer", "value": potong(", ".join(d["developers"][:2]), 100), "inline": True})
        rilis = (d.get("release_date") or {}).get("date")
        if rilis:
            fields.append({"name": "Rilis", "value": rilis, "inline": True})
        meta = (d.get("metacritic") or {}).get("score")
        if meta:
            fields.append({"name": "Metacritic", "value": str(meta), "inline": True})
        plat = d.get("platforms", {})
        p = [n for k, n in (("windows", "Windows"), ("mac", "macOS"), ("linux", "Linux")) if plat.get(k)]
        if p:
            fields.append({"name": "Platform", "value": ", ".join(p), "inline": True})
        gambar = d.get("header_image", "")
        warna = 0x1B2838
    else:
        el = o["el"]
        if el.get("description"):
            desc += "\n\n" + potong(el["description"], 220)
        if (el.get("seller") or {}).get("name"):
            fields.append({"name": "Publisher", "value": potong(el["seller"]["name"], 100), "inline": True})
        gambar = o.get("image", "")
        warna = 0x313131

    fields.append({"name": "Ulasan Steam", "value": teks_ulasan(rv), "inline": False})
    if lainnya:
        teks = "\n".join(f'{x["store"]}: {rupiah(x["price"])} (-{x["disc"]}%)' for x in lainnya)
        fields.append({"name": "Dibanding toko lain (lebih mahal)", "value": teks, "inline": False})

    return {
        "title": ("🔥 " if low else "") + o["name"], "url": o["url"], "description": desc,
        "color": warna, "fields": fields, "image": {"url": gambar},
        "footer": {"text": f'{o["store"]} • dicek ' + datetime.now().strftime("%d/%m %H:%M")},
    }


def siklus_diskon():
    log("=== Mulai pengecekan diskon ===")
    seen = load_seen(D_SEEN_FILE, D_TTL)

    # --- 1. kumpulkan penawaran ---
    offers = []
    if D_CEK_STEAM:
        try:
            offers += steam_offers(seen)
            catat(WEBHOOK_DISKON, seen, "Steam", True)
        except Exception as e:
            log("Steam gagal:", repr(e))
            catat(WEBHOOK_DISKON, seen, "Steam", False)
    if D_CEK_EPIC:
        try:
            offers += epic_offers()
            catat(WEBHOOK_DISKON, seen, "Epic", True)
        except Exception as e:
            log("Epic gagal:", repr(e))
            catat(WEBHOOK_DISKON, seen, "Epic", False)

    if not offers:
        log("Tidak ada penawaran baru yang lolos filter.")
        save_seen(D_SEEN_FILE, seen)
        return

    # --- 2. dedupe antar toko: ambil yang termurah ---
    grup = {}
    for o in offers:
        grup.setdefault(norm(o["name"]), []).append(o)
    antrean = []
    for kunci, lst in grup.items():
        lst.sort(key=lambda x: x["price"])
        menang, kalah = lst[0], lst[1:]
        if MAKS_HARGA and menang["price"] > MAKS_HARGA:
            continue
        if MIN_HARGA and menang["price"] < MIN_HARGA:
            continue
        if kalah:
            log(f'Duplikat "{menang["name"]}": pilih {menang["store"]} {rupiah(menang["price"])}, '
                f'buang {", ".join(x["store"] + " " + rupiah(x["price"]) for x in kalah)}')
        antrean.append((kunci, menang, kalah, lst))
    antrean.sort(key=lambda x: -x[1]["disc"])

    # --- 3. filter kualitas lalu kirim ---
    batch, pending, ping_batch, pertama, terkirim = [], [], False, True, 0

    def flush():
        nonlocal batch, pending, ping_batch, pertama, terkirim
        if not batch:
            return
        header = "🎮 **Diskon game baru!**" if pertama else None
        if kirim(WEBHOOK_DISKON, batch, header, role_id=ROLE_DISKON, ping=ping_batch):
            t = time.time()
            for kunci, menang, lst in pending:
                seen["games"][kunci] = {"price": menang["price"], "store": menang["store"], "t": t}
                for x in lst:
                    seen["steam"][x["key"]] = t
            terkirim += len(batch)
            save_seen(D_SEEN_FILE, seen)
            pertama = False
        batch, pending, ping_batch = [], [], False
        time.sleep(1)

    for kunci, menang, kalah, lst in antrean:
        lama = seen["games"].get(kunci)
        if lama and menang["price"] >= lama["price"] * 0.999:
            for x in lst:
                seen["steam"][x["key"]] = time.time()
            continue
        if any(x["key"] in seen["tolak"] for x in lst):
            continue
        if terkirim + len(batch) >= MAKS_BARU:
            log(f"Batas {MAKS_BARU} game per siklus tercapai, sisanya nanti.")
            break

        rv = ambil_ulasan(menang)
        ok, alasan = lolos_kualitas(menang, rv)
        if not ok:
            log(f'Ditolak: {menang["name"]} ({alasan})')
            for x in lst:
                seen["tolak"][x["key"]] = time.time()
            continue

        low = itad_terendah(menang["name"], menang["price"]) if ITAD_KEY else None
        log(f'Kirim: {menang["name"]} [{menang["store"]}] -{menang["disc"]}% {rupiah(menang["price"])}'
            f'{" 🔥LOW" if low else ""}')
        batch.append(buat_embed(menang, kalah, rv, low))
        pending.append((kunci, menang, lst))
        if menang["disc"] >= PING_DISKON or low:
            ping_batch = True
        if len(batch) >= D_PER_PESAN:
            flush()

    flush()
    save_seen(D_SEEN_FILE, seen)
    log(f"Selesai (diskon). Terkirim: {terkirim}")


# =====================================================================
#                              MAIN
# =====================================================================
def bagian_aktif():
    """Daftar (nama, webhook, fungsi siklus, pesan tes) sesuai opsi --gratis / --diskon."""
    semua = [
        ("gratis", WEBHOOK_GRATIS, siklus_gratis, "✅ Tes webhook berhasil. Bot game gratis siap."),
        ("diskon", WEBHOOK_DISKON, siklus_diskon, "✅ Tes webhook berhasil. Bot diskon game siap."),
    ]
    pilih = [n for n in ("gratis", "diskon") if f"--{n}" in sys.argv]
    return [b for b in semua if not pilih or b[0] in pilih]


def siklus_semua():
    """Satu putaran: jalankan semua bagian aktif. Error satu bagian tidak menghentikan bagian lain."""
    for nama, webhook, fn, _ in bagian_aktif():
        if not webhook:
            continue
        try:
            fn()
        except TidakAdaInternet:
            raise
        except Exception as e:
            log(f"Error bagian {nama}:", repr(e))


if __name__ == "__main__":
    aktif = [b for b in bagian_aktif() if b[1]]
    if not aktif:
        sys.exit("Webhook belum diisi di file .env (WEBHOOK_GRATIS / WEBHOOK_DISKON / WEBHOOK)")
    if "--tes" in sys.argv:
        for nama, webhook, _, pesan in aktif:
            kirim_teks(webhook, pesan)
        sys.exit()
    if "--sekali" in sys.argv:
        siklus_semua()
        sys.exit()
    log(f"Bot jalan ({' + '.join(b[0] for b in aktif)}), cek tiap {INTERVAL_MENIT} menit. Ctrl+C untuk berhenti.")
    jalankan_terus(siklus_semua, INTERVAL_MENIT)
