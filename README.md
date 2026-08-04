# Viral Intel 3.0

O Viral Intel investiga por que um vídeo, carrossel, imagem ou texto ficou acima ou abaixo do desempenho habitual do próprio perfil. A análise separa rigorosamente quatro camadas:

1. **Fatos observados** — números do Insights, comentários públicos e propriedades da mídia.
2. **Métricas calculadas** — fórmulas transparentes, sem transformar dado ausente em zero.
3. **Benchmark do perfil** — comparação com posts do mesmo formato e estágio de vida.
4. **Hipóteses testáveis** — explicações possíveis, sempre com evidência, confiança e limite.

O sistema não promete “decifrar” o código interno de Instagram, TikTok ou YouTube. Ele usa os dados do próprio perfil para decidir entre repetir, iterar, mudar ou reunir mais informação.

## Arquitetura de produção

- Gemini usa análise multimodal com saída estruturada validada por Pydantic.
- A recuperação da Gemini ocorre em três níveis: saída tipada, Interactions API e JSON validado localmente.
- O sistema alterna entre modelos compatíveis quando a rota principal falha.
- OpenAI e Anthropic permanecem disponíveis como provedores alternativos configuráveis.
- Falhas da IA ou da coleta pública nunca derrubam o relatório completo.
- O motor determinístico continua entregando cálculos, baseline e limitações quando nenhum provedor responde.
- Nenhuma chave é mostrada na interface, incluída nos relatórios ou preservada nos erros técnicos.

## O que o painel analisa

- Upload direto de vídeo, imagem, captura ou slides.
- Link público complementar do Instagram, TikTok, YouTube, Threads ou Facebook.
- Métricas privadas do Insights, incluindo alcance, compartilhamentos, salvamentos, retenção e conclusão.
- Histórico CSV para construir a mediana real do próprio perfil.
- Vídeo local com FFmpeg: duração, resolução, proporção, FPS, áudio, cortes e frames representativos.
- Imagens e carrosséis: dimensões, proporção, brilho, entropia visual e leitura multimodal.
- Perfil por formato, tema, tipo de gancho, CTA, cadência e melhores posts.

Uma captura estática de reel ou vídeo é aceita como **análise parcial**. Nesse caso, o sistema deixa explícito que ritmo, áudio, cortes e retenção temporal não foram medidos. Um único slide de carrossel também é tratado como leitura incompleta, sem inventar o restante da sequência.

## Resultado entregue

- Interpretação do desempenho com qualidade dos dados visível.
- Causas prováveis com evidências, confiança e limitações.
- Plano do próximo conteúdo com ganchos, estrutura, legenda e CTA.
- Experimentos que alteram uma variável por vez.
- Ledger de evidências com IDs rastreáveis.
- Downloads em JSON e Markdown.
- Diagnóstico técnico de recuperação quando algum provedor falha.

## Instalação no Mac

Requisitos: Python 3.11 ou 3.12 e FFmpeg. O instalador detecta Python incompatível e, quando o Homebrew está disponível, instala automaticamente Python 3.12 e FFmpeg.

```bash
cd ~/viral-intel
chmod +x setup.sh run.sh
./setup.sh
```

Depois, abra `.env` e adicione pelo menos uma chave. Para iniciar:

```bash
cd ~/viral-intel
./run.sh
```

O navegador abrirá o painel. Não é necessário mover vídeos para uma pasta fixa; os arquivos são enviados diretamente na tela.

O nome da pasta pode ser `viral-intel`, `viral-intel2` ou outro. Os scripts descobrem automaticamente a pasta em que estão. Em Macs Intel, as dependências binárias permanecem compatíveis com Python 3.12 e o PyArrow local é fixado para evitar regressões conhecidas nesse ambiente.

## Como obter uma análise realmente forte

1. Exporte ou digite as métricas privadas do post.
2. Envie o vídeo original ou todos os slides na ordem correta.
3. Envie um CSV com pelo menos 10 posts comparáveis.
4. Compare números capturados no mesmo estágio: 6h com 6h, 24h com 24h, 7d com 7d.
5. Depois da recomendação, altere uma variável por vez e acompanhe a métrica definida.

Use `data/profile_template.csv` como modelo. Percentuais devem estar na escala humana: `42.5` significa 42,5%. Células vazias permanecem indisponíveis.

## Estrutura

```text
app/analysis/       cálculos, baseline, CSV e ledger
app/ai/             schemas, guardrails e provedores resilientes
app/media/          inspeção local de vídeo e imagem
app/online/         coleta pública complementar
app/pipeline/       orquestração tolerante a falhas
app/reporting/      exportação JSON e Markdown
app/ui/             painéis Streamlit
cloud/              entrypoint e dependências de produção
tests/              unidade, integração e smoke tests
```

## Segurança e privacidade

- `.env`, Secrets do Streamlit, ambiente virtual, mídia e relatórios ficam fora do Git.
- Uploads, frames e relatórios temporários são apagados no modo de nuvem.
- URLs aceitas são limitadas às plataformas suportadas.
- A coleta pública é best-effort e nunca substitui os Insights do proprietário.
- Cookies só devem ser usados em contas e conteúdos autorizados.
- Erros de provedores têm chaves removidas antes de serem exibidos.

## Validação

O CI executa duas rotas independentes:

1. ambiente completo de desenvolvimento;
2. ambiente exato do Streamlit Cloud, usando `cloud/requirements.txt`.

```bash
python -m ruff check app cloud tests
python -m ruff format --check app cloud tests
python -m pip check
python -m compileall -q app cloud tests
python -m unittest discover -s tests -v
```

Os smoke tests abrem `cloud/streamlit_app.py` e fazem um upload real no painel de produção.

## Deploy no Streamlit Community Cloud

- arquivo principal: `cloud/streamlit_app.py`;
- Python: 3.12;
- dependências: `cloud/requirements.txt`;
- dependência Linux: `packages.txt` com FFmpeg;
- Secret obrigatório para leitura multimodal: `GOOGLE_API_KEY` na raiz do TOML.

O entrypoint possui uma tela de diagnóstico para falhas de inicialização. O modo de nuvem desativa a transcrição Whisper local para respeitar a memória gratuita e mantém o relatório somente na sessão até o download.

## Fontes metodológicas oficiais

- [Instagram — como a classificação funciona](https://about.instagram.com/blog/announcements/instagram-ranking-explained)
- [Instagram — recomendações e originalidade](https://creators.instagram.com/blog/recommendations-and-originality)
- [Meta — métricas de Insights](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights)
- [TikTok — por que um vídeo é recomendado](https://newsroom.tiktok.com/en-us/learn-why-a-video-is-recommended-for-you)
- [YouTube — alcance, impressões e watch time](https://support.google.com/youtube/answer/9314486)
- [YouTube — momentos-chave de retenção](https://support.google.com/youtube/answer/9314415)
- [OpenAI — Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI — Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Gemini — saída estruturada](https://ai.google.dev/gemini-api/docs/structured-output)
- [Anthropic — modelos atuais](https://docs.anthropic.com/en/docs/about-claude/models/overview)
