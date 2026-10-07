# 🔧 Plano de Ação: Ajustes no Bot ALETO

## 1. Restrição de Comando (/verificar)
- **Objetivo:** Impedir que usuários comuns forcem leitura no site, sobrecarregando a infraestrutura.
- **Implementação:** Adicionar verificação `chat_id == settings.TELEGRAM_ADMIN_CHAT_ID` dentro do `verificar_command` em `src/bot/handlers.py`.

## 2. Ajuste de Frequência de Leitura
- **Objetivo:** Alterar checagem de 30 min para 5 min.
- **Implementação:** Alterar `CHECK_INTERVAL_MINUTES=30` para `CHECK_INTERVAL_MINUTES=5` no `.env` e ajustar o `scheduler` em `src/main.py`.

## 3. Implementação de Botões Inline (Melhoria de UX)
- **Objetivo:** Facilitar a interação.
- **Implementação:** Adicionar teclado `InlineKeyboardMarkup` ao final do resumo diário com botões:
  - `[🔍 Status]`
  - `[📋 Termos]`
  - `[📥 Último]`
- **Custo/Benefício:** Alto valor, baixa complexidade (usar `telegram.InlineKeyboardButton`).

---

### Execução Imediata
Vou aplicar a restrição do comando e o ajuste de tempo agora. Você concorda em subir esses dois agora e depois faremos os botões em um segundo momento para testar a estabilidade?
