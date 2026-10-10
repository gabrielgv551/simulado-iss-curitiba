# Simulado ISS Curitiba

Site de simulados da banca FAFIPA para o concurso Auditor Fiscal de Tributos
Municipais (Prefeitura de Curitiba 5/2026). Flask serverless, deploy na
Vercel, dados no PostgreSQL da VPS.

## Variáveis de ambiente (configurar no painel da Vercel)

| Variável | Descrição |
|---|---|
| `VPS_PG_HOST` | IP/host do PostgreSQL |
| `VPS_PG_PORT` | porta (padrão 5432) |
| `VPS_PG_DBNAME` | nome do banco (padrão `iss_curitiba`) |
| `VPS_PG_USER` | usuário do banco |
| `VPS_PG_PASSWORD` | senha do banco |
| `SITE_PASSWORD` | senha de acesso ao site |
| `FLASK_SECRET` | chave aleatória para as sessões |

## Rodar local

```bash
pip install -r requirements.txt
python api/index.py
```
