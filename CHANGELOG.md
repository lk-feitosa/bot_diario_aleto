# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste ficheiro.

O formato está baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e a versão será compatível com [Semantic Versioning](https://semver.org/lang/pt-BR/).

---

## [V8.1.0] - 2026-10-05

### Melhoria - Segurança e Múltiplo Env/EnvVar (Token)

- **Correção de exposição de token** → O token completo do Telegram NÃO é mais exibido em logs de produção
- **Mask de token em logs** → logs mostram apenas 12 primeiros caracteres dele: `8641526184:AAHb...` (ou `***` se não configurado)
- **Validação preventiva** → O bot tenta inicializar o token ANTES do polling, permitindo falhar bem antes de tentar conectar ao Telegram e expor completo
- **Explicação clara de token necessário** → Mensagens avisam explicitamente onde configurar (arquivo `.env` ou Render Config Environment Variables)

### Melhoria - Observabilidade

- **Logging estruturado JSON** → quando `JSON_LOGS=1` ou ambiente `RENDER` está definido, logs são em JSON (timestamp + level + logger + message + exception)
- **Message de Health Check** → agora mostra apenas primeiros 12 caracteres do token, evitando expor completo

---

## [V8.0.0] - 2026-10-05

### Adição - Infraestrutura/Produto

- Documentação de persistência SQLite após restart no Render (#61)
- Healthcheck HTTP via thread separado (porta 8080)
- Implementação de observabilidade básica (logs JSON)

---