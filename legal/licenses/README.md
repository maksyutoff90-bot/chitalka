# Лицензии компонентов

Здесь лежат тексты лицензий, взятые из установленных пакетов и их
`dist-info/licenses`. Версии зафиксированы на 2026-11-07.

| Компонент | Версия | Лицензия | Файл |
| --- | --- | --- | --- |
| Python | 3.11 | PSF License | `python-LICENSE.txt` |
| Python third-party | 3.11 | OpenSSL, expat, libffi, zlib и др. | `python-thirdparty-license.html` |
| Tcl/Tk | 8.6 | BSD-подобная | `tcl-tk-LICENSE.terms` |
| Pillow | 10.3.0 | HPND | `pillow-LICENSE` |
| lxml | 6.1.3 | BSD-3-Clause | `lxml/LICENSE.txt`, `lxml/LICENSES.txt` |
| pypdfium2 | 5.15.0 | BSD-3-Clause, Apache-2.0 | `pypdfium2/LICENSES/` |
| PDFium | 159.0.8146.0 | BSD-3-Clause | `pypdfium2/BUILD_LICENSES/pdfium.txt` |
| tkinterdnd2 | 0.7.0 | MIT | `tkinterdnd2-LICENSE` |
| TkDND | в составе tkinterdnd2 | Tcl/Tk-подобная | `tkdnd-LICENSE.txt` |
| PyInstaller | 6.22.3 | GPL-2.0+ с исключением | `pyinstaller-COPYING.txt` |
| FreeDict / WikDict | 2025.11.23 | CC BY-SA 3.0 | `../../data/dictionaries/LICENSE-CC-BY-SA.txt` |

`pypdfium2` поставляет PDFium и набор сборочных зависимостей; их тексты лежат
в `pypdfium2/BUILD_LICENSES/`. Для коммерческой поставки сохраняйте эту папку
целиком. `python-thirdparty-license.html` покрывает OpenSSL, expat, libffi,
zlib и другие библиотеки, которые Python/Windows могут включать в сборку.

## Что важно

- **PyMuPDF** в runtime и в `tools/make_samples.py` не используется.
  Демо-PDF уже лежит в `data/books`; при необходимости пересборки используйте
  отдельный инструмент с подходящей лицензией.
- **FreeDict** требует атрибуции и share-alike для изменённых производных.
- **PyInstaller** разрешает собирать и распространять несвободные программы,
  включая коммерческие.
- Перед релизом сверьте версии с `requirements.txt` и проверьте тексты лицензий
  у юриста.
