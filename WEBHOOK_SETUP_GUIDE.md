# Настройка Webhook для Worker Tracker Bot

Этот документ содержит инструкции по настройке Webhook для Telegram бота.

## Требования

- Публично доступный домен/сервер с HTTPS (можно использовать Cloudflare Tunnel или ngrok)
- Токен Telegram бота (получается у @BotFather)

## Настройка с использованием Cloudflare Tunnel

1. Установите Cloudflare Tunnel:
   ```
   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared.deb
   ```

2. Запустите Cloudflare Tunnel, указав порт вашего приложения:
   ```
   cloudflared tunnel --url http://localhost:5003
   ```

3. Скопируйте полученный URL и укажите его в файле `.env`:
   ```
   WEBHOOK_URL=https://ваш-туннель-cloudflare.trycloudflare.com
   PORT=5003
   BOT_MODE=webhook
   ```

4. Запустите бота в режиме webhook:
   ```
   python run_webhook_port_5003.py
   ```

## Настройка с использованием ngrok

1. Установите и настройте ngrok

2. Запустите ngrok, указав порт вашего приложения:
   ```
   ngrok http 5003
   ```

3. Скопируйте полученный URL и укажите его в файле `.env`:
   ```
   WEBHOOK_URL=https://ваш-туннель-ngrok.io
   PORT=5003
   BOT_MODE=webhook
   ```

4. Запустите бота в режиме webhook:
   ```
   python run_webhook_port_5003.py
   ```

## Проверка настройки webhook

Для проверки корректности настройки webhook, выполните:

```
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

Вы должны увидеть ответ, подтверждающий что ваш webhook URL настроен и активен.

## Важные замечания

- Убедитесь, что порт в URL webhook'а и в настройках сервера совпадают
- При использовании нескольких ботов, используйте разные порты для каждого бота
- Webhook требует HTTPS для работы с Telegram API
