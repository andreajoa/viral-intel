# Viral Intel 5.0

O Viral Intel é um **motor de inteligência de conteúdo orientado por evidências**. Ele investiga o desempenho de vídeos, Reels, Shorts, carrosséis, imagens e textos sem transformar correlação em causalidade e sem fingir acesso aos pesos privados dos algoritmos.

A V5 muda o foco de uma análise isolada para um sistema que pode **aprender com o próprio perfil ao longo do tempo**: cria um baseline robusto, encontra conteúdos historicamente semelhantes (Content Twins), acumula snapshots do mesmo post e preserva um ledger auditável de fatos, cálculos, comparações e hipóteses.

## Princípios centrais

1. **Dado ausente nunca vira zero.**
2. **Fato observado, cálculo, benchmark e hipótese são entidades diferentes.**
3. **Não existe um limiar universal de viralização.** O baseline é construído a partir do comportamento do próprio perfil.
4. **Correlação não prova causa.** Hipóteses precisam apontar evidências e indicar o que falta para confirmação.
5. **A plataforma não expõe seu score privado de ranking.** O sistema reconstrói somente o que pode ser sustentado pelas evidências disponíveis.
6. **O modelo de IA não é a fonte da verdade.** Métricas e cálculos passam primeiro pelo motor determinístico; afirmações de performance podem ser submetidas a verificação independente.

## O que há de novo na V5

### Baseline robusto do perfil

O benchmark não classifica mais posts usando regras universais como `1,5× = acima` ou `3× = viral`. As métricas de contas sociais têm distribuição muito assimétrica, por isso a V5 modela os comparáveis em `log1p` e usa mediana, MAD e IQR para estimar:

- faixa esperada de desempenho;
- percentil do post;
- anomalia robusta (z robusto);
- dispersão do baseline;
- força da evidência conforme o tamanho da amostra.

A razão para a mediana continua disponível porque é intuitiva, mas não é mais a regra principal de classificação.

### Creative Fingerprint

Cada análise pode produzir uma impressão digital criativa determinística baseada somente em atributos observados:

- plataforma e formato;
- tema/pilar;
- tipo e texto do gancho;
- mecanismos criativos;
- emoção;
- estilo visual;
- estrutura/progressão;
- CTA;
- duração;
- orientação;
- áudio;
- densidade de cortes.

Esses atributos não recebem importância causal automaticamente. Eles servem para comparação histórica e desenho de experimentos.

### Content Twins

Quando existe memória longitudinal, o Viral Intel procura conteúdos anteriores semelhantes e permite comparar o post com um grupo mais específico do que simplesmente “todos os Reels”. A similaridade combina sinais textuais, criativos e técnicos e permanece explicitamente **descritiva, não causal**.

### Memória longitudinal

No modo persistente, cada relatório pode alimentar uma base SQLite local com:

- perfil;
- post;
- timestamp do snapshot;
- métricas;
- benchmark;
- Creative Fingerprint;
- relatório completo;
- experimentos planejados e concluídos.

Isso permite analisar novamente o mesmo conteúdo e observar sua trajetória ao longo do tempo em vez de trabalhar apenas com uma fotografia final.

> No Streamlit Community Cloud o modo padrão é efêmero e a persistência fica desativada. Para uso contínuo em produção, a camada de storage deve ser conectada a um banco persistente externo. O contrato de análise foi mantido separado para permitir essa evolução sem reescrever o motor.

### Vídeo multimodal nativo + FFmpeg

A V5 mantém FFmpeg como camada técnica auditável para medir duração, FPS, resolução, áudio, loudness, cortes e frames. Quando configurado, o vídeo original também pode ser enviado diretamente ao Gemini para leitura temporal nativa, permitindo observar:

- primeiro segundo;
- intervalo de 1–3 segundos;
- progressão do corpo;
- relação entre fala, texto e mudanças visuais;
- fechamento.

A leitura multimodal descreve a execução criativa; ela **não transforma ritmo em retenção medida** e não substitui os Insights do proprietário.

## Camadas da investigação

1. **Fatos observados** — mídia, métricas, conta autorizada, comentários e dados fornecidos.
2. **Métricas calculadas** — fórmulas transparentes, sem preencher lacunas artificialmente.
3. **Baseline robusto** — comparação com o comportamento do próprio perfil e estágio de vida do post.
4. **Creative Fingerprint e Content Twins** — comparação com conteúdos historicamente parecidos.
5. **Inteligência dos comentários** — intenções, perguntas, marcações, linguagem e emoção da amostra disponível.
6. **Trajetória de distribuição** — elegibilidade, resposta inicial, circulação, expansão e conversão quando os dados sustentarem essas etapas.
7. **Hipóteses testáveis** — explicações concorrentes com evidências, limitações e dados necessários para confirmação.
8. **Memória longitudinal** — snapshots do post e aprendizado acumulado do perfil.

## Acesso oficial ao Instagram

Para mídias pertencentes a uma conta profissional autenticada, o painel pode consultar a API oficial da Meta em modo somente leitura. Dependendo das permissões e métricas disponíveis, pode obter:

- dados da conta profissional;
- legenda, formato, data e permalink;
- alcance, visualizações, impressões e interações agregadas;
- compartilhamentos, salvamentos, visitas ao perfil e seguidores atribuídos quando expostos pela API;
- comentários retornados para a mídia autorizada;
- publicações recentes para benchmark.

A coleta de Insights usa **requisições em lote com fallback seletivo**: se a API rejeitar um grupo de métricas, o coletor divide o lote progressivamente até isolar os campos incompatíveis. Também há retry/backoff limitado para 429 e falhas transitórias.

A API **não fornece** ao Viral Intel:

- identidade individual de quem curtiu;
- identidade individual de quem salvou ou compartilhou;
- score de ranking atribuído a cada pessoa;
- peso exato de likes, saves, shares, retenção ou qualquer outro sinal;
- motivo exato de cada impressão.

O sistema não tenta contornar esses limites por scraping invasivo.

## O que o painel aceita

- vídeo original;
- imagem ou captura;
- todos os slides de um carrossel;
- link público complementar;
- acesso oficial opcional ao Instagram profissional administrado pelo usuário;
- comentários em CSV/JSON ou capturas autorizadas;
- métricas manuais dos Insights;
- histórico CSV;
- identificador de perfil para memória longitudinal em análises manuais/TikTok/YouTube.

## Resultado entregue

- conclusão executiva;
- qualidade/cobertura dos dados;
- faixa esperada e posição do post no baseline;
- análise da peça e progressão criativa;
- Content Twins quando houver histórico;
- linha do tempo de snapshots quando houver mais de uma análise do post;
- reconstrução da distribuição somente nas etapas sustentadas;
- leitura dos comentários disponíveis;
- hipóteses com evidências e limitações;
- plano do próximo conteúdo;
- experimentos de uma variável por vez;
- ledger auditável;
- exportação JSON e Markdown.

## Instalação no Mac

Requisitos: Python 3.11 ou 3.12 e FFmpeg.

```bash
cd ~/viral-intel
chmod +x setup.sh run.sh
./setup.sh
```

Configure ao menos uma chave de IA no `.env` para ativar a leitura multimodal. O motor determinístico continua funcionando sem chave.

```bash
cd ~/viral-intel
./run.sh
```

O script local usa o mesmo bootstrap de produção do Streamlit Cloud para reduzir divergências entre ambientes.

## Configuração principal

```env
AI_PROVIDER=auto
GOOGLE_API_KEY=
GEMINI_MODEL=gemini-3.7-flash
GEMINI_FALLBACK_MODELS=gemini-3.6-flash,gemini-3.5-flash-lite

ENABLE_NATIVE_VIDEO_AI=true
NATIVE_VIDEO_MAX_MB=200

ENABLE_PERSISTENCE=true
INTELLIGENCE_DB=./data/viral_intel.sqlite3
CONTENT_TWIN_LIMIT=8
CONTENT_TWIN_MIN_SCORE=0.35

ENABLE_INSTAGRAM_GRAPH=true
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_USER_ID=
INSTAGRAM_API_VERSION=v25.0
INSTAGRAM_HISTORY_LIMIT=50
INSTAGRAM_MAX_RETRIES=3
INSTAGRAM_BACKOFF_SECONDS=1
```

Consulte `.env.example` para todas as opções.

## Como obter uma análise forte

1. Use a mídia original sempre que possível.
2. Autorize a conta profissional ou forneça os Insights completos.
3. Use timestamps equivalentes: compare 6h com 6h, 24h com 24h e assim por diante.
4. Alimente pelo menos 10–15 conteúdos comparáveis para fortalecer o baseline.
5. Use um identificador estável de perfil quando a análise não vier de uma conta oficial autenticada.
6. Analise o mesmo post novamente em momentos diferentes para construir a trajetória.
7. Teste uma variável por vez e registre o resultado do experimento.

Percentuais usam escala humana: `42.5` significa 42,5%. Células vazias permanecem indisponíveis.

## Estrutura

```text
app/analysis/       métricas, baseline robusto, fingerprints, comentários e evidências
app/ai/             observação multimodal, schemas, estrategista e verificação de claims
app/media/          FFmpeg, frames, áudio e transcrição local
app/online/         conectores oficiais e coleta pública complementar
app/pipeline/       orquestração evidence-first
app/storage/        memória longitudinal e experimentos
app/reporting/      exportação JSON e Markdown
app/ui/             painel Streamlit V5
cloud/              bootstrap do Streamlit Cloud
tests/              unidade, integração e smoke tests
```

## Segurança e privacidade

- `.env`, Secrets, bancos SQLite, uploads e relatórios temporários ficam fora do Git.
- O modo Cloud é efêmero por padrão.
- Arquivos temporários de mídia são removidos após a análise.
- Vídeos enviados à API multimodal são apagados proativamente após o processamento quando a API permite.
- Tokens são removidos de mensagens de erro conhecidas.
- A API oficial é usada somente em contas/mídias autorizadas.
- Usernames de comentários só permanecem quando vieram de uma fonte fornecida ou autorizada.
- Nenhuma característica demográfica ou sensível é inferida de usernames.

## Validação

```bash
python -m ruff check app cloud tests
python -m ruff format --check app cloud tests
python -m pip check
python -m compileall -q app cloud tests
python -m unittest discover -s tests -v
```

O CI também abre o bootstrap do Streamlit Cloud e executa um upload real no dashboard.

## Deploy no Streamlit Community Cloud

- arquivo principal: `cloud/streamlit_app.py`;
- dashboard: `app/ui/dashboard_v5.py`;
- Python: 3.12;
- dependências: `cloud/requirements.txt`;
- FFmpeg: `packages.txt`;
- Secret mínimo para IA: `GOOGLE_API_KEY`;
- Secrets opcionais: `INSTAGRAM_ACCESS_TOKEN` e `INSTAGRAM_USER_ID`.

## Fontes metodológicas oficiais

- [Instagram — como a classificação funciona](https://about.instagram.com/blog/announcements/instagram-ranking-explained)
- [Instagram — recomendações e originalidade](https://creators.instagram.com/blog/recommendations-and-originality)
- [Meta — Instagram API](https://developers.facebook.com/docs/instagram-platform)
- [Meta — métricas de Insights](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights)
- [Meta — comentários de mídia](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/comment-moderation)
- [TikTok Developers](https://developers.tiktok.com/)
- [YouTube Analytics API](https://developers.google.com/youtube/analytics)
- [Gemini — vídeo](https://ai.google.dev/gemini-api/docs/video-understanding)
- [Gemini — saída estruturada](https://ai.google.dev/gemini-api/docs/structured-output)
