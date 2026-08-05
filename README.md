# Viral Intel 4.0

O Viral Intel investiga por que um vídeo, carrossel, imagem ou texto ficou acima ou abaixo do desempenho habitual do próprio perfil. A análise não se limita a descrever a arte: ela separa conteúdo, público, conta, distribuição e conversão.

## Camadas da investigação

1. **Fatos observados** — mídia, métricas, conta autorizada e comentários disponíveis.
2. **Métricas calculadas** — fórmulas transparentes, sem transformar ausência em zero.
3. **Benchmark do perfil** — comparação com posts do mesmo formato e estágio de vida.
4. **Inteligência dos comentários** — intenções, perguntas, marcações, linguagem e emoção da amostra.
5. **Trajetória de distribuição** — elegibilidade, resposta inicial, circulação, não seguidores e conversão.
6. **Hipóteses testáveis** — explicações concorrentes com confiança, limite e dado necessário para confirmação.

O sistema não afirma conhecer o código interno do Instagram. Feed, Reels, Explorar, Stories e recomendações usam sistemas diferentes. O relatório reconstrói o caminho mais provável apenas a partir das evidências disponíveis.

## Acesso oficial ao Instagram

Para mídias pertencentes a uma conta profissional autenticada, o painel pode consultar a API oficial da Meta em modo somente leitura. Dependendo das permissões e métricas disponíveis, ele pode obter:

- dados públicos da conta profissional;
- legenda, formato, data e permalink da publicação;
- alcance, visualizações, impressões e interações agregadas;
- compartilhamentos, salvamentos, visitas ao perfil e seguidores atribuídos quando expostos pela API;
- comentários e usernames dos comentadores retornados pela conta autorizada;
- publicações recentes para construir um benchmark automático.

A API **não fornece** ao aplicativo:

- a identidade individual de quem curtiu;
- a identidade de quem salvou ou compartilhou;
- o score de ranking atribuído a cada pessoa;
- o peso exato de likes, saves, shares, retenção ou outros sinais;
- o motivo exato de cada impressão.

Esses limites aparecem no painel e no relatório. O aplicativo nunca tenta contorná-los por scraping invasivo.

### Variáveis opcionais

```env
ENABLE_INSTAGRAM_GRAPH=true
INSTAGRAM_ACCESS_TOKEN=seu_token
INSTAGRAM_USER_ID=id_da_conta_profissional
INSTAGRAM_API_VERSION=v25.0
MAX_INSTAGRAM_COMMENTS=300
INSTAGRAM_HISTORY_LIMIT=20
```

Também é possível informar token, ID da conta e ID da mídia apenas durante a execução. O token não é gravado no relatório.

## O que o painel analisa

- Upload de vídeo, imagem, captura ou slides.
- Link público complementar do Instagram, TikTok, YouTube, Threads ou Facebook.
- Acesso oficial opcional a uma conta profissional administrada pelo usuário.
- Comentários autorizados pela API ou enviados em CSV/JSON.
- Métricas privadas do Insights, incluindo origem da distribuição e conversão.
- Histórico CSV ou histórico autorizado para construir a mediana do perfil.
- Vídeo local com FFmpeg: duração, proporção, FPS, áudio, cortes e frames.
- Imagens e carrosséis: proporção, composição e leitura multimodal.

Uma captura estática de Reel ou vídeo continua sendo uma análise parcial. Ela não permite medir ritmo, áudio, cortes ou retenção temporal. Imagens estáticas não possuem uma métrica pública de retenção de leitura equivalente à de vídeo.

## Resultado entregue

- conclusão executiva com qualidade dos dados;
- matriz do que estava e não estava disponível;
- investigação por etapas da distribuição;
- causas prováveis com evidências, confiança e limitações;
- análise visível da peça, público, comentários, conta e histórico;
- plano do próximo conteúdo com ganchos, estrutura, legenda e CTA;
- experimentos que alteram uma variável por vez;
- ledger auditável e downloads em JSON e Markdown.

## Instalação no Mac

Requisitos: Python 3.11 ou 3.12 e FFmpeg.

```bash
cd ~/viral-intel
chmod +x setup.sh run.sh
./setup.sh
```

Depois, configure ao menos uma chave de IA no `.env` e execute:

```bash
cd ~/viral-intel
./run.sh
```

## Como obter uma análise realmente forte

1. Autorize a conta profissional ou digite os Insights completos.
2. Envie a mídia original ou todos os slides na ordem.
3. Forneça comentários exportados quando a API não os retornar.
4. Use pelo menos 10 posts comparáveis.
5. Compare snapshots no mesmo estágio: 6h com 6h, 24h com 24h e 7d com 7d.
6. Confirme elegibilidade no Status da Conta, originalidade e existência de mídia paga.
7. Teste uma variável por vez após o diagnóstico.

Percentuais usam escala humana: `42.5` significa 42,5%. Células vazias permanecem indisponíveis.

## Estrutura

```text
app/analysis/       métricas, comentários, distribuição, benchmark e ledger
app/ai/             schemas, guardrails e provedores resilientes
app/media/          inspeção local de vídeo e imagem
app/online/         API oficial e coleta pública complementar
app/pipeline/       orquestração tolerante a falhas
app/reporting/      exportação JSON e Markdown
app/ui/             painel Streamlit
cloud/              runtime do Streamlit Cloud
tests/              unidade, integração e smoke tests
```

## Segurança e privacidade

- `.env`, Secrets, tokens, uploads e relatórios temporários ficam fora do Git.
- O modo de nuvem apaga uploads, frames e arquivos temporários após a análise.
- A API oficial é usada somente em contas e mídias autorizadas.
- Usernames de comentários só aparecem quando já vieram de uma fonte autorizada.
- Nenhuma característica demográfica ou sensível é inferida a partir de usernames.
- Chaves e tokens são removidos de mensagens de erro.

## Validação

```bash
python -m ruff check app cloud tests
python -m ruff format --check app cloud tests
python -m pip check
python -m compileall -q app cloud tests
python -m unittest discover -s tests -v
```

O CI também abre o entrypoint do Streamlit Cloud e realiza um upload real no painel.

## Deploy no Streamlit Community Cloud

- arquivo principal: `cloud/streamlit_app.py`;
- Python: 3.12;
- dependências: `cloud/requirements.txt`;
- Linux: `packages.txt` com FFmpeg;
- Secret mínimo: `GOOGLE_API_KEY`;
- Secrets opcionais: `INSTAGRAM_ACCESS_TOKEN` e `INSTAGRAM_USER_ID`.

## Fontes metodológicas oficiais

- [Instagram — como a classificação funciona](https://about.instagram.com/blog/announcements/instagram-ranking-explained)
- [Instagram — recomendações e originalidade](https://creators.instagram.com/blog/recommendations-and-originality)
- [Meta — Instagram API](https://developers.facebook.com/docs/instagram-platform)
- [Meta — métricas de Insights](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights)
- [Meta — comentários de mídia](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/comment-moderation)
- [TikTok — por que um vídeo é recomendado](https://newsroom.tiktok.com/en-us/learn-why-a-video-is-recommended-for-you)
- [YouTube — alcance e watch time](https://support.google.com/youtube/answer/9314486)
- [Gemini — saída estruturada](https://ai.google.dev/gemini-api/docs/structured-output)
