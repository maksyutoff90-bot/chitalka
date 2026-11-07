# Подпись Windows exe: варианты и цены

Обновлено: 2026-11-07. Цены — ориентиры, а не оферта; проверяйте у CA.

## Коротко

- **Бесплатно подписать можно только самоподписанным сертификатом** — Windows
  ему не доверяет, SmartScreen ругается. Для продажи это не решение.
- **Commercial Code Signing Certificate не бесплатен**: ориентир
  **$99–$400 в год** за OV/standard; EV — дороже.
- **Microsoft Store** сейчас берёт **0 за регистрацию** аккаунта, но это не
  Code Signing сертификат: Store сам подписывает пакет и берёт комиссию с продаж.
- **Azure Artifact Signing** — $9.99/мес, но для физлиц только US/Canada;
  для России как физлицо не подходит. Для организации — только 12 регионов,
  России в списке нет.

## Варианты

| Вариант | Цена | Кому подходит | Минусы |
| --- | --- | --- | --- |
| Самоподписанный | 0 | тесты | Windows не доверяет, SmartScreen |
| OV/standard Code Signing | ~$99–$300/год | ИП/ООО, физлица | нужен токен/HSM, проверка личности |
| EV Code Signing | ~$299–$700/год | если требует закупка | дороже; SmartScreen не обходит |
| Azure Artifact Signing | $9.99/мес Basic | US/Canada individuals; orgs в 12 регионах | России нет; Azure paid subscription |
| Microsoft Store | 0 за аккаунт | MSIX-приложение | сертификация Store, комиссия |
| Open-source CA | 0 | только OSS-проекты | закрытый коммерческий продукт не подходит |

## OV/standard

Обычный Code Signing Certificate:

- подтверждает издателя;
- подписывает exe/installer;
- ключ должен храниться в hardware token/HSM (CA/B Forum);
- у некоторых CA — облачный HSM (например, Certum SimplySign);
- PFX-файл как единственный носитель ключа больше не соответствует современным
  требованиям; используйте хранилище сертификатов Windows и `/sha1`.

Ориентиры:

- Certum standard — около **$99/год** (у партнёров);
- Sectigo/GlobalSign/DigiCert — обычно **$200–$500/год**;
- токен/доставка/облачный HSM — иногда включены, иногда +$30–$150.

## EV

EV подтверждает организацию строже. Для small desktop-продукта чаще всего
**не нужен**: SmartScreen больше не даёт мгновенный «траст» только за EV.
Берите, если EV требует магазин, закупка или партнёр.

## Azure Artifact Signing

- Basic: **$9.99/мес**, 5 000 подписей;
- Premium: **$99.99/мес**, 100 000 подписей;
- нужен платный Azure subscription;
- физлица — только US/Canada;
- организации — 12 регионов, России нет;
- сертификат и ключ не выдаются, экспорт невозможен;
- подписывает Windows-форматы, не Java.

Для продавца из России это **не основной путь**.

## Microsoft Store

По официальной странице Microsoft, регистрация индивидуального разработчика
сейчас **без взноса**. Store принимает MSIX-пакет и подписывает его сам.
Но:

- нужен MSIX, а не просто portable exe;
- сертификация и правила Store;
- комиссия с продаж;
- не все функции/форматы могут пройти проверку.

Это способ выпустить подписанный продукт без покупки сертификата, но не замена
Code Signing для сайта/прямых продаж.

## Что делать из России

1. Проверить, принимает ли выбранный CA российского физлица/ИП.
2. Запросить OV-сертификат на 1 год.
3. Уточнить, как хранится ключ: токен, облачный HSM, SimplySign.
4. Проверить оплату и доставку токена.
5. Подписать exe и installer, использовать timestamp.
6. Не покупать EV без требования.

Ориентир бюджета: **$100–$300 в год** + возможная доставка токена.
Российские сертификаты УЦ не обязательно будут доверены Windows/SmartScreen —
проверяйте это отдельно.

## Полезные ссылки

- [Microsoft Artifact Signing pricing](https://azure.microsoft.com/en-us/pricing/details/artifact-signing/)
- [Microsoft Store developer account](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account?tabs=individual)
- [Sectigo Code Signing](https://www.sectigo.com/ssl-certificates-tls/code-signing)
- [Сравнение Azure и CA-сертификата](https://my-ssl.com/learn/azure-trusted-signing-vs-code-signing-certificate)
- [CA/B Forum Code Signing Requirements](https://cabforum.org/working-groups/code-signing/requirements/)

## Наш скрипт

`tools/sign_exe.ps1` поддерживает:

- `CHITALKA_CERT_THUMBPRINT` — сертификат в хранилище Windows;
- `CHITALKA_CERT_PFX` + пароль — старый PFX;
- timestamp и проверку подписи.

Пример:

```powershell
$env:CHITALKA_CERT_THUMBPRINT = "ABCDEF..."
powershell -ExecutionPolicy Bypass -File tools\sign_exe.ps1
```

Самоподписанный сертификат можно создать бесплатно, но для продажи он
не подходит.
