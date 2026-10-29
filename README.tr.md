# devdust

**Projelerinizin geride bıraktığı build çıktılarını ve cache'leri bulun — sonra güvenle silin.**

[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](https://www.python.org)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

<img src="docs/demo.svg" alt="devdust örnek bir çalışma alanında temizlenebilir klasörleri listeliyor" width="720">

`devdust` projelerinizi tarar, bulduğu her `node_modules`, `__pycache__`,
`.next`, `target` ve `.venv` klasörünü bildirir, kaç GB yer tuttuğunu söyler ve
**yalnızca siz istediğinizde**, yalnızca size gösterilen klasörleri siler.

- **Varsayılan olarak kuru çalışma (dry run).** `--delete` olmadan hiçbir şey silinmez.
- **İki güven seviyesi.** Yeniden üretilmesi ucuz cache'ler `safe`; `build/`,
  `bin/`, `vendor/` gibi ismi tartışmalı klasörler `review` ve siz açıkça
  istemedikçe listeye girmez.
- **Akıllı budama.** Bir klasör eşleştiğinde boyutu bir kez ölçülür, içine
  girilmez; böylece toplamlar dürüst kalır ve tarama hızlı olur.
- **Sıfır bağımlılık.** Tek `pip install`, denetlenecek tedarik zinciri yok.

---

## Kurulum

```console
$ pipx install devdust        # önerilen: izole, her zaman PATH'te
$ uv tool install devdust     # ya da uv ile
$ pip install devdust         # ya da mevcut ortama
```

Depodan:

```console
$ git clone https://github.com/OWNER/devdust.git
$ cd devdust
$ pipx install .
```

Linux ve macOS'ta Python 3.9+. Windows denenmedi (yol işlemleri platformdan
bağımsız, ama testler yalnızca POSIX'te koşuyor).

## Hızlı başlangıç

```console
$ devdust                     # bulunduğunuz dizinde kuru çalışma
$ devdust ~/work ~/oss        # birden fazla kök dizin
$ devdust --min-size 100MB    # sadece büyük olanlar
$ devdust --older-than 90d    # 3 aydır dokunulmamış cache'ler
$ devdust --delete            # gördüklerinizi silin (onay ister)
```

`--delete` verene kadar her şey bir rapordur:

<img src="docs/demo-delete.svg" alt="devdust klasörleri siliyor" width="720">

## Neleri bulur?

| Tür | Örnekler |
| --- | --- |
| `python` | `__pycache__`, `.venv`, `venv`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, `.nox`, `*.egg-info`, `.hypothesis` |
| `node` | `node_modules`, `.next`, `.nuxt`, `.svelte-kit`, `.turbo`, `.parcel-cache`, `.vite`, `.angular`, `bower_components` |
| `rust` | `target` |
| `java` | `.gradle`, `out` |
| `dotnet` | `bin`, `obj` |
| `ios` / `swift` | `Pods`, `DerivedData`, `.build` |
| `terraform` | `.terraform`, `.terragrunt-cache` |
| `generic` | `build`, `dist`, `vendor`, `.cache` |

Güncel ve tam liste için:

```console
$ devdust rules
```

## Güvenlik modeli

Klasör silmek sağduyu gerektirir; `devdust`'un kendi kuralları var:

1. **Varsayılan kuru çalışma.** `--delete` gerekir ve yalnızca ekrana basılan
   kayıtlar silinir (`--top 25` 25 kayıt basar, 25 tanesini siler — hepsi için
   `--top 0`).
2. **İsmi tartışmalı olanlar ikinci onay ister.** `build/`, `bin/`, `obj/`,
   `target/`, `vendor/` gibi klasörler `review` seviyesindedir: sadece
   `--include-review` ile listelenir.
3. **Taranan kökler asla aday olmaz.** `devdust`'u bir `node_modules`
   klasörüne yönlendirirseniz, o klasörün kendisini silmeyi önermez. `$HOME`,
   çalışma dizini ve dosya sistemi kökü de korunur.
4. **Sembolik linkler ne izlenir ne silinir.** `/` hedefini gösteren bir link
   "kazanılabilir alan"ı şişiremez, veri kaybına da dönüşemez.
5. **Yollar taranan kökün içinde olmak zorunda.** Aksi hâlde silme koruması
   reddeder.
6. **Hata tek klasörle sınırlı kalır.** Yazılamayan bir kayıt çalışmayı
   durdurmaz; stderr'e raporlanır ve çıkış koduna yansır. Salt-okunur ağaçlar
   bir kez açılır ve yeniden denenir.

## Kullanım

```
devdust [PATH ...] [seçenekler]
```

| Seçenek | Ne yapar |
| --- | --- |
| `--delete` | Gösterilen klasörleri siler (varsayılan: sadece rapor) |
| `-y`, `--yes` | Onay sorusunu atlar (stdin TTY değilse zorunlu) |
| `--include-review` | `build/`, `bin/`, `target/` gibi isimleri de değerlendirir |
| `--kinds LIST` | Ekosistem filtresi, örn. `--kinds node,python` |
| `--exclude GLOB` | Bu glob'a uyan klasörleri atlar (tekrarlanabilir) |
| `--min-size SIZE` | `SIZE`'dan küçük eşleşmeleri yok sayar (`50MB`, `1.5g`, `512`) |
| `--older-than AGE` | Yalnızca `AGE` boyunca dokunulmamış olanlar (`30d`, `12h`, `2w`) |
| `--max-depth N` | Kökün altında `N` seviyeden fazla derine inmez |
| `--top N` | En fazla `N` kayıt gösterir; `0` hepsi (varsayılan `25`) |
| `--sort {size,age,path,kind}` | Sıralama (varsayılan: en büyük önce) |
| `--json` | Makine okunur çıktı (`--top` ile kısaltılmaz) |
| `--color {auto,always,never}` | Renk denetimi; `NO_COLOR` / `FORCE_COLOR` da dikkate alınır |
| `--version` | Sürümü yazar |
| `rules` (alt komut) | Bilinen tüm desenleri listeler |

Çıkış kodları: `0` başarılı, `1` tarama veya silme hatası, `2` hatalı kullanım.

### JSON çıktısı

```console
$ devdust ~/work --json | jq '.totals'
{
  "size": 812345678,
  "size_human": "775 MB",
  "files": 43120,
  "directories": 12
}
```

Her kayıt `path`, `size`, `size_human`, `files`, `age_seconds`, `age_human`,
`kind`, `confidence` ve eşleşen `rule` alanlarını taşır. `--delete` ile birlikte
`removed` bloğu da (kazanılan bayt, silinen klasör sayısı, hatalar) çıktıya eklenir.

## Tarifler

```bash
# üç aydır el sürülmemiş, 50 MB üstü klasörlerin aylık temizliği
devdust ~/code --min-size 50MB --older-than 90d --delete

# CI runner'ında build öncesi yer açmak
devdust . --exclude .git --kinds node --delete --yes

# diski tam olarak ne yiyor?
devdust ~ --top 0 --sort size --min-size 10MB

# zamanda yolculuk: geçen yıldan beri dokunulmamış projeler
devdust ~/code --sort age --top 10
```

Kabuğunuza bir alias koymak en sık senaryoyu iki harfe indirir:

```bash
alias dd='devdust ~/code --min-size 20MB'
```

## Geliştirme

```console
$ make install     # editable kurulum + dev bağımlılıkları
$ make test        # pytest
$ make lint        # ruff check + ruff format --check
$ make demo        # docs/demo*.svg dosyalarını gerçek CLI çıktısından üretir
```

Demo görselleri `scripts/render_demo_svg.py` ile gerçek çıktıdan üretilir;
böylece dokümantasyon koddan kopmaz. `scripts/make_demo_tree.py` ise bu
görsellerin kaynağı olan sahte çalışma alanını kurar.

Dizin yapısı:

```
src/devdust/
  cli.py          argümanlar, çıktı, çıkış kodları
  scanner.py      dolaşma, boyut hesabı, güvenlik korumaları, silme
  rules.py        desen tablosu ve güven seviyeleri
  formatting.py   boyut, yaş, renk, tablo
tests/            birim + uçtan uca testler; ağ yok, diskte fixture yok
```

Yeni bir desen eklemek `src/devdust/rules.py` içinde tek satırlık bir iştir;
ayrıntılar [CONTRIBUTING.md](CONTRIBUTING.md).

## SSS

**Neden `npkill` / `cargo clean` / `rm -rf` değil?**
Onlar tek bir ekosistemi kapsar. `devdust` tüm çalışma alanını tek geçişte
tarar, muhakeme edilebilir bir güvenlik modeli sunar ve script'ler için makine
okunur çıktı verir.

**Sembolik linkleri izler mi?**
Hayır, asla. Link'li klasörler ölçüm sırasında atlanır ve silme koruması
tarafından reddedilir.

**`.gitignore`'a uyar mı?**
Hayır. `devdust` klasör isimlerine bakar, depo kurallarına değil. Görmezden
gelinen ama cache'e benzeyen yollar yine raporlanır (genelde istediğiniz budur);
`.git/` içine hiç girilmez.

**Boyutlar "görünen" boyut mu, diskte kapladığı mı?**
Görünen boyut: her dosyanın `st_size` toplamı, yani `du --apparent-size`. Clone,
reflink veya hardlink kullanan dosya sistemlerinde (APFS, Btrfs, `pnpm` store)
geri kazanacağınız alan gösterilenden az olabilir.

## Lisans

MIT — [LICENSE](LICENSE) dosyasına bakın.

---

<sub>English documentation: [README.md](README.md)</sub>
