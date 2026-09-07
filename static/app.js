
let currentData = null;
let currentHeadline = null;
let currentLink = null;

const $ = id => document.getElementById(id);
const setBox = (id, html, type="") => {
  const el = $(id);
  el.className = type ? type : "";
  el.innerHTML = html || "";
};

$("image").addEventListener("change", e => {
  const f = e.target.files[0];
  if (!f) return;
  $("preview").src = URL.createObjectURL(f);
  $("previewWrap").classList.remove("hidden");
});

$("analyzeBtn").addEventListener("click", async () => {
  const image = $("image").files[0];
  const link = $("link").value.trim();
  if (!image || !link) {
    setBox("status","Envie o print e o link de afiliado.","error");
    return;
  }
  $("analyzeBtn").disabled = true;
  setBox("status","Lendo a oferta...");
  const fd = new FormData();
  fd.append("image", image);
  fd.append("affiliate_link", link);
  try {
    const r = await fetch("/api/analyze",{method:"POST",body:fd});
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "Erro ao analisar");
    currentData = j.data;
    currentLink = link;

    $("product").value = currentData.product_title_clean || "";
    $("priceFrom").value = currentData.price_from || "";
    $("priceTo").value = currentData.price_to || "";
    $("payment").value = currentData.payment_type || "none";
    $("installments").value = currentData.installments || "";
    $("coupon").value = currentData.coupon || "";
    $("editCard").classList.remove("hidden");

    if (j.blocked) {
      setBox("warning", j.blocked_reason, "error");
      $("generateBtn").disabled = true;
    } else {
      let msg = "";
      if (j.yesterday) msg = `Ontem: R$ ${j.yesterday.price}.`;
      setBox("warning", msg, msg ? "ok" : "");
      $("generateBtn").disabled = false;
    }
    setBox("status","Oferta lida. Confira os campos.","ok");
    $("editCard").scrollIntoView({behavior:"smooth",block:"start"});
  } catch (e) {
    setBox("status", e.message, "error");
  } finally {
    $("analyzeBtn").disabled = false;
  }
});

function collectData(){
  return {
    ...currentData,
    product_title_clean: $("product").value.trim(),
    price_from: $("priceFrom").value ? Number($("priceFrom").value) : null,
    price_to: Number($("priceTo").value),
    payment_type: $("payment").value,
    installments: $("installments").value ? Number($("installments").value) : null,
    coupon: $("coupon").value.trim() || null
  };
}

$("generateBtn").addEventListener("click", async () => {
  const data = collectData();
  $("generateBtn").disabled = true;
  $("generateBtn").textContent = "Gerando...";
  try {
    const r = await fetch("/api/generate",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({data, affiliate_link: currentLink})
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "Erro ao gerar");
    currentData = data;
    currentHeadline = j.headline;
    $("result").value = j.message;
    $("resultCard").classList.remove("hidden");
    $("resultCard").scrollIntoView({behavior:"smooth",block:"start"});
  } catch(e){
    setBox("warning",e.message,"error");
  } finally {
    $("generateBtn").disabled = false;
    $("generateBtn").textContent = "Gerar promoção";
  }
});

$("copyBtn").addEventListener("click", async () => {
  try{
    await navigator.clipboard.writeText($("result").value);
    $("copyBtn").textContent = "Copiado!";
    setTimeout(()=>$("copyBtn").textContent="Copiar",1300);
  }catch{
    $("result").select();
    document.execCommand("copy");
  }
});

$("saveBtn").addEventListener("click", async () => {
  try{
    const r = await fetch("/api/save",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        data: currentData,
        affiliate_link: currentLink,
        headline: currentHeadline
      })
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "Erro ao salvar");
    $("count").textContent = `${j.stats.mine}/${j.stats.goal}`;
    setBox("saveStatus","Salva no histórico de hoje.","ok");
  }catch(e){
    setBox("saveStatus",e.message,"error");
  }
});

$("importBtn").addEventListener("click", async () => {
  const text = $("groupText").value.trim();
  if(!text){ setBox("importStatus","Cole as promoções primeiro.","error"); return; }
  $("importBtn").disabled = true;
  try{
    const r = await fetch("/api/import-group",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text,day:$("groupDay").value})
    });
    const j = await r.json();
    if(!j.ok) throw new Error(j.error || "Erro ao importar");
    setBox("importStatus",`${j.imported} promoções importadas.`,"ok");
  }catch(e){ setBox("importStatus",e.message,"error"); }
  finally{$("importBtn").disabled=false;}
});

$("historyBtn").addEventListener("click", async () => {
  const r = await fetch("/api/history");
  const j = await r.json();
  $("count").textContent = `${j.stats.mine}/${j.stats.goal}`;
  $("history").innerHTML = j.items.map(x => `
    <div class="history-item">
      <strong>${x.product_clean}</strong>
      <span>${x.promo_date} · R$ ${x.price_to} · ${x.source}</span>
    </div>
  `).join("") || '<p class="muted">Sem histórico ainda.</p>';
});
