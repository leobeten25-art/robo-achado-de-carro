
# Robô Achado de Carro — Mobile V1

Versão feita para usar pelo celular no navegador.

## Fluxo

1. Tire uma foto ou selecione um print da promoção.
2. Cole seu link de afiliado.
3. Toque em **Analisar oferta**.
4. Confira/edite nome, preços, Pix/parcelamento e cupom.
5. Toque em **Gerar promoção**.
6. Copie o texto pronto para o WhatsApp.
7. Toque em **Aprovar e salvar** para alimentar o histórico.

## Regras já implementadas

- Meta: 40 promoções/dia.
- Preserva o link de afiliado informado.
- Limpa títulos muito grandes.
- Preços sem centavos (sem arredondar para cima).
- `no Pix` para Pix.
- `em 6x` (ou a quantidade exibida) para parcelamento.
- Cupom como `🎟️ Use o Cupom: *CÓDIGO*`.
- Remove a linha do cupom quando não existe.
- Bloqueia produto parecido que já apareceu hoje.
- Se apareceu ontem, bloqueia quando o preço atual está pior.
- Permite colar as mensagens dos outros curadores de hoje/ontem.
- Gera a HEAD no padrão Achado de Carro.

## Para colocar online

Este projeto precisa ficar hospedado em um servidor porque a chave da API da OpenAI
não deve ficar exposta no navegador.

Uma opção simples é o Render:

1. Crie uma conta no Render.
2. Crie um novo **Web Service** usando este projeto em um repositório GitHub.
3. Configure:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn -b 0.0.0.0:$PORT app:app`
4. Em **Environment**, crie:
   - `OPENAI_API_KEY` = sua chave da API
   - `OPENAI_MODEL` = um modelo com visão disponível na sua conta
5. Publique.
6. Abra a URL gerada no celular.
7. No navegador, use **Adicionar à tela inicial** para ficar parecendo um app.

## Persistência do histórico

Por padrão a V1 salva em SQLite (`achado_carro.db`).

Em muitos serviços de hospedagem, o disco local pode ser apagado quando o app
reinicia. Para uso diário sério, configure um disco persistente/volume no seu
provedor e defina a variável:

`DB_PATH=/caminho/persistente/achado_carro.db`

Sem isso, a interface funciona, mas o histórico pode não ser permanente.

## Segurança

Nunca coloque sua `OPENAI_API_KEY` dentro de `app.js`, HTML ou qualquer arquivo
que seja enviado ao navegador. Nesta versão a chave fica apenas no servidor.
