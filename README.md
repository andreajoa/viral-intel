# Viral Intel 2.1

O Viral Intel investiga por que um vídeo, carrossel, imagem ou texto ficou acima ou
abaixo do desempenho habitual do próprio perfil. A versão 2.0 foi reconstruída para
separar quatro coisas que antes apareciam misturadas:

1. **Fatos observados** — números do Insights, comentários públicos e propriedades da mídia.
2. **Métricas calculadas** — fórmulas transparentes, sem transformar dado ausente em zero.
3. **Benchmark do perfil** — comparação com posts do mesmo formato e estágio de vida.
4. **Hipóteses** — explicações possíveis, sempre com evidência, confiança e limite.

O sistema não promete “decifrar” o código interno de Instagram, TikTok ou YouTube.
Ele usa os dados do seu perfil para testar hipóteses e decidir entre repetir, iterar,
mudar ou reunir mais informação.

## O que mudou

- Gemini usa análise multimodal por `generateContent`, saída JSON estruturada e
  fallback automático entre modelos compatíveis configurados para a conta.
- OpenAI usa Responses API e saída estruturada; Gemini e Anthropic também usam schema.
- Toda hipótese precisa citar IDs reais do ledger (`O`, `C`, `B` ou `T`).
- Referências inexistentes são removidas e a hipótese é rebaixada para não avaliável.
- Posts são comparados ao mesmo formato e, quando possível, ao mesmo estágio de vida.
- Perfil analisado por formato, tema, tipo de gancho, CTA, cadência e top posts.
- Vídeo medido localmente com FFmpeg: duração, resolução, proporção, FPS, áudio,
  cortes, frames do início/meio/fim e transcrição opcional.
- Imagens e carrosséis têm dimensões, proporção, brilho e entropia visual registrados.
- O painel aceita upload direto, link complementar, métricas privadas e histórico CSV.
- O painel impede que uma imagem seja analisada como reel/vídeo e que um único slide
  seja tratado como carrossel.
- Relatórios completos podem ser baixados em JSON e Markdown.
- Sem chave de IA, o motor determinístico continua útil e honesto.

## Instalação no Mac

Requisitos: Python 3.11 ou 3.12 e FFmpeg. O instalador detecta Python 3.14 e,
quando o Homebrew está disponível, instala automaticamente o Python 3.12 e o FFmpeg.

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

O navegador abrirá o painel. Não é mais necessário mover vídeos para uma pasta fixa:
você pode enviá-los diretamente na tela.

O nome da pasta pode ser `viral-intel`, `viral-intel2` ou outro. Os scripts descobrem
automaticamente a pasta em que estão. Se existir um `.venv` criado com Python 3.14,
o instalador o preserva com o nome `.venv-incompativel-<data>` e cria um novo com
Python 3.12. Em Macs Intel, as dependências binárias são fixadas em versões que ainda
oferecem wheels para Python 3.12/macOS 10.15+. O PyArrow permanece na versão 16.0.0
para evitar o segfault conhecido em macOS 11 Intel nas versões seguintes.

## Como obter uma análise realmente forte

1. Exporte ou digite as métricas privadas do post.
2. Envie o vídeo ou os slides originais.
3. Envie um CSV com pelo menos 10 posts do mesmo formato.
4. Compare números capturados no mesmo estágio: 6h com 6h, 24h com 24h, 7d com 7d.
5. Depois da recomendação, altere uma variável por vez e acompanhe a métrica definida.

Use `data/profile_template.csv` como modelo. Percentuais devem estar na escala humana:
`42.5` significa 42,5%. Células vazias permanecem indisponíveis.

O formato escolhido precisa corresponder ao arquivo: reel/short/vídeo exige um arquivo
de vídeo; carrossel exige dois ou mais slides; imagem exige um único arquivo de imagem.
Uma captura estática de um reel não permite medir gancho temporal, ritmo ou transcrição.

## Estrutura

```text
app/analysis/       cálculos, baseline, CSV e ledger
app/ai/             schema, guardrails e provedores
app/media/          inspeção local de vídeo/imagem
app/online/         coleta pública complementar
app/pipeline/       orquestração e persistência
app/reporting/      exportação JSON/Markdown
app/ui/             painel Streamlit
tests/              testes do núcleo e regressões
```

## Fontes metodológicas oficiais

- [Instagram — como a classificação funciona](https://about.instagram.com/blog/announcements/instagram-ranking-explained)
- [Instagram — recomendações e originalidade](https://creators.instagram.com/blog/recommendations-and-originality)
- [Meta — métricas de Insights](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights)
- [TikTok — por que um vídeo é recomendado](https://newsroom.tiktok.com/en-us/learn-why-a-video-is-recommended-for-you)
- [YouTube — alcance, impressões e watch time](https://support.google.com/youtube/answer/9314486)
- [YouTube — momentos-chave de retenção](https://support.google.com/youtube/answer/9314415)
- [OpenAI — Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI — Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Gemini — modelos e saída estruturada](https://ai.google.dev/gemini-api/docs/structured-output)
- [Anthropic — modelos atuais](https://docs.anthropic.com/en/docs/about-claude/models/overview)

## Segurança e privacidade

- `.env`, ambiente virtual, mídia enviada e relatórios novos ficam fora do Git.
- Nenhuma chave é mostrada no painel ou gravada no relatório.
- A coleta por link é best-effort e não substitui Insights do proprietário.
- Use cookies somente de contas e conteúdos que você está autorizado a acessar.
- Relatórios, mídias, históricos e exportações locais permanecem fora do Git.

## Validação

```bash
python -m unittest discover -s tests -v
python -m compileall -q app tests
```
