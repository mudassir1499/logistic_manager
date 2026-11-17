"""Blog articles: working out what an import actually costs, and paying for it."""

CATEGORY = {
    'name': 'Costs & Payments',
    'slug': 'costs-payments',
    'description': 'Landed cost, CBM, freight maths and how to pay Chinese suppliers without losing money.',
    'display_order': 4,
}

POSTS = [
    {
        'slug': 'how-to-calculate-landed-cost-china-to-uae',
        'title': 'How to Calculate Landed Cost from China to the UAE',
        'category': 'costs-payments',
        'featured': True,
        'excerpt': 'The supplier’s unit price is typically 60–75% of what a unit actually costs you on the shelf. Here is the full build-up, line by line, with a worked example.',
        'meta_description': 'A complete landed cost calculation for UAE importers buying from China: every cost line from factory price to warehouse, with a worked example and a per-unit formula.',
        'keywords': 'landed cost calculation, import cost China to UAE, total cost of import Dubai, landed cost formula, calculate import cost per unit',
        'body': """
<p>The most common pricing mistake in importing is setting a retail price against the supplier's quote. The factory price is usually somewhere between 60% and 75% of what a unit really costs by the time it is sitting in your warehouse, sellable.</p>

<p>Landed cost is the total of every cost required to get one sellable unit into your possession. Work it out properly once, and pricing, margin and whether the product is worth importing at all become straightforward questions.</p>

<h2>The full cost stack</h2>

<h3>1. Goods</h3>
<ul>
  <li>Unit price × quantity</li>
  <li>Tooling or mould cost, if any — amortise this across the units you realistically expect to produce from it, not just the first order</li>
  <li>Sample costs, including courier</li>
  <li>Custom packaging and plate setup charges</li>
</ul>

<h3>2. Origin costs in China</h3>
<ul>
  <li>Inland haulage from factory to port</li>
  <li>Export clearance and documentation</li>
  <li>Origin terminal handling</li>
  <li>Certificate of origin issuance and any attestation</li>
</ul>
<p>Under FOB these sit with the supplier and are inside the quoted price. Under EXW they are yours, which is why an EXW quote that looks cheaper often is not.</p>

<h3>3. Quality control</h3>
<ul>
  <li>Pre-shipment inspection</li>
  <li>Re-inspection if the first one fails (budget for the possibility)</li>
  <li>Laboratory testing where certification requires it</li>
</ul>

<h3>4. Freight</h3>
<ul>
  <li>Ocean or air freight</li>
  <li>Fuel and currency adjustment factors, and any peak-season surcharge</li>
  <li>Cargo insurance</li>
</ul>

<h3>5. Destination costs in the UAE</h3>
<ul>
  <li>Destination terminal handling</li>
  <li>Deconsolidation, for LCL</li>
  <li>Customs brokerage</li>
  <li>Port storage, if clearance is not immediate</li>
  <li>Demurrage or detention, if things go wrong</li>
</ul>

<h3>6. Duty and taxes</h3>
<ul>
  <li>Customs duty on the CIF value</li>
  <li>Import VAT on CIF plus duty — a <em>cost</em> if you are not VAT-registered, a <em>cash flow item</em> if you are and can recover it</li>
  <li>Excise, if your category attracts it</li>
</ul>

<h3>7. Inland and warehousing</h3>
<ul>
  <li>Transport from port to your warehouse</li>
  <li>Unloading and handling</li>
  <li>Storage until sold</li>
  <li>Relabelling or repacking, if required</li>
</ul>

<h3>8. The lines everyone forgets</h3>
<ul>
  <li><strong>Defect allowance.</strong> Some units will be unsellable. If your AQL allows 2.5% major defects, that is 2.5% of your units gone — and the cost lands on the remainder.</li>
  <li><strong>Bank charges and FX spread.</strong> Wire fees plus the margin on the currency conversion. On a large order the spread is not trivial.</li>
  <li><strong>Certification.</strong> Testing and certificate issuance, amortised across the production life of the model.</li>
  <li><strong>Cost of capital.</strong> Money paid as a deposit is committed for the whole production and transit period — commonly two to three months on a sea shipment.</li>
</ul>

<h2>A worked example</h2>

<p>2,000 units of a consumer product, sea freight, VAT-registered importer, standard 5% duty. All figures USD and illustrative.</p>

<div class="blog-table-wrap">
<table>
  <thead>
    <tr><th>Line</th><th>Amount</th><th>Per unit</th></tr>
  </thead>
  <tbody>
    <tr><td>Goods @ 8.40 × 2,000</td><td>16,800.00</td><td>8.400</td></tr>
    <tr><td>Custom packaging setup</td><td>420.00</td><td>0.210</td></tr>
    <tr><td>Samples and courier</td><td>180.00</td><td>0.090</td></tr>
    <tr><td>Pre-shipment inspection</td><td>310.00</td><td>0.155</td></tr>
    <tr><td>Sea freight (LCL, ~11 CBM)</td><td>1,760.00</td><td>0.880</td></tr>
    <tr><td>Insurance</td><td>110.00</td><td>0.055</td></tr>
    <tr><td><strong>CIF value</strong></td><td><strong>18,670.00</strong></td><td>9.335</td></tr>
    <tr><td>Customs duty @ 5% of CIF</td><td>933.50</td><td>0.467</td></tr>
    <tr><td>Destination handling + deconsolidation</td><td>540.00</td><td>0.270</td></tr>
    <tr><td>Customs brokerage</td><td>190.00</td><td>0.095</td></tr>
    <tr><td>Transport to warehouse</td><td>230.00</td><td>0.115</td></tr>
    <tr><td>Bank charges and FX spread</td><td>165.00</td><td>0.083</td></tr>
    <tr><td><strong>Total cost</strong></td><td><strong>20,728.50</strong></td><td><strong>10.364</strong></td></tr>
    <tr><td>Defect allowance @ 2.5% (1,950 sellable)</td><td>—</td><td><strong>10.630</strong></td></tr>
  </tbody>
</table>
</div>

<p>Landed cost is <strong>10.63</strong> against a supplier price of <strong>8.40</strong>. The factory price was 79% of the true cost — and this example had no tooling, no certification and no demurrage. On a first order for a regulated product, the factory price can easily be under 60% of landed cost.</p>

<p>Note that import VAT is excluded from the cost total here because the importer is registered and recovers it. It is still roughly a thousand dollars of cash going out at the port, which has to be financed even though it is not a cost.</p>

<h2>The per-unit formula</h2>

<blockquote><p>Landed cost per unit = (Goods + Origin + QC + Freight + Insurance + Duty + Destination + Inland + Financing) ÷ Sellable units</p></blockquote>

<p>The denominator matters as much as the numerator. Dividing by units <em>ordered</em> rather than units <em>sellable</em> is how a product that looked profitable turns out not to be.</p>

<h2>Using it properly</h2>

<h3>Compare suppliers on landed cost, not unit price</h3>
<p>A supplier 5% cheaper per unit whose cartons are 20% bulkier will cost you more delivered. Volume drives freight, and freight is a large line.</p>

<h3>Test the packaging</h3>
<p>Reducing carton size is one of the highest-return changes available on a bulky product. Ask the factory what the cost would be to redesign the inner packing to fit more per carton, and run the freight numbers both ways. On low-density goods this frequently saves more than any price negotiation.</p>

<h3>Model the order quantity</h3>
<p>Fixed costs — tooling, setup, inspection, brokerage — spread across more units. Run the landed cost at several quantities before deciding how much to order. The curve is usually steep at the low end and flattens quickly.</p>

<h3>Recalculate every order</h3>
<p>Freight rates move substantially. A landed cost calculated in a soft market and never revisited will quietly stop being true.</p>

<h2>Related reading</h2>
<ul>
  <li><a href="/blog/cbm-and-volumetric-weight-explained/">CBM and volumetric weight explained</a> — how the freight line is actually calculated</li>
  <li><a href="/blog/uae-customs-duty-and-vat-on-imports-from-china/">UAE customs duty and VAT</a> — the duty and tax lines in detail</li>
  <li><a href="/blog/air-vs-sea-freight-china-to-uae/">Air vs sea freight</a> — choosing the mode that minimises total cost, not just freight cost</li>
</ul>
""",
    },
    {
        'slug': 'cbm-and-volumetric-weight-explained',
        'title': 'CBM and Volumetric Weight Explained',
        'category': 'costs-payments',
        'excerpt': 'Freight is charged on space as often as on weight. Understanding the two formulas lets you check a quote, and shows you where packaging changes save real money.',
        'meta_description': 'How to calculate CBM for sea freight and volumetric weight for air freight, why chargeable weight differs from actual weight, and how packaging affects cost.',
        'keywords': 'CBM calculation, volumetric weight formula, chargeable weight air freight, how to calculate CBM shipping, cubic meter freight',
        'body': """
<p>Carriers do not sell weight. They sell capacity — and capacity is limited by both space and payload. A ship or aircraft can fill up on volume long before it reaches its weight limit, so freight pricing has to account for both.</p>

<p>Two calculations do that: <strong>CBM</strong> for sea, and <strong>volumetric weight</strong> for air. Neither is complicated, and being able to do them yourself means you can check a quote and spot where a packaging change would pay for itself.</p>

<h2>CBM — cubic metres</h2>

<blockquote><p>CBM = Length (m) × Width (m) × Height (m)</p></blockquote>

<p>Measure the <strong>outer carton</strong>, not the product. If dimensions are in centimetres, divide the result by 1,000,000.</p>

<p><strong>Example.</strong> A carton measuring 60 × 40 × 35 cm:</p>
<p>0.60 × 0.40 × 0.35 = <strong>0.084 CBM</strong> per carton.<br>
For 250 cartons: 0.084 × 250 = <strong>21 CBM</strong>.</p>

<h3>The revenue tonne</h3>

<p>LCL sea freight is charged on whichever is greater — your CBM or your metric tonnes. This is written as W/M (weight or measure) and the result is the "revenue tonne".</p>

<div class="blog-table-wrap">
<table>
  <thead>
    <tr><th>Shipment</th><th>CBM</th><th>Tonnes</th><th>Charged on</th></tr>
  </thead>
  <tbody>
    <tr><td>Cushions</td><td>18</td><td>2.1</td><td>18 (volume)</td></tr>
    <tr><td>Ceramic tiles</td><td>6</td><td>9.4</td><td>9.4 (weight)</td></tr>
    <tr><td>Small appliances</td><td>12</td><td>11.6</td><td>12 (volume)</td></tr>
  </tbody>
</table>
</div>

<p>Roughly speaking: if your cargo weighs less than one tonne per cubic metre, volume bills. Above that, weight bills.</p>

<h2>Volumetric weight — air freight</h2>

<blockquote><p>Volumetric kg = Length (cm) × Width (cm) × Height (cm) ÷ 6000</p></blockquote>

<p>Express couriers (DHL, FedEx, UPS) generally divide by <strong>5000</strong> instead, which produces a higher figure — bulky parcels are meaningfully more expensive on express than on standard air freight.</p>

<p><strong>Example.</strong> The same 60 × 40 × 35 cm carton, gross weight 12 kg:</p>
<ul>
  <li>Air freight: 60 × 40 × 35 ÷ 6000 = <strong>14 kg volumetric</strong></li>
  <li>Express: 60 × 40 × 35 ÷ 5000 = <strong>16.8 kg volumetric</strong></li>
</ul>

<p>Actual weight is 12 kg, so you pay on 14 kg by air freight or 16.8 kg by express. The difference between those two figures on a 250-carton shipment is substantial.</p>

<h3>Chargeable weight</h3>

<p>Chargeable weight is whichever is higher — actual gross or volumetric. Always. There is no scenario in which you pay the lower one.</p>

<h2>Density is the number that decides your mode</h2>

<blockquote><p>Density (kg per CBM) = Gross weight (kg) ÷ Volume (CBM)</p></blockquote>

<p>This single figure tells you a great deal:</p>

<div class="blog-table-wrap">
<table>
  <thead>
    <tr><th>Density</th><th>Character</th><th>Implication</th></tr>
  </thead>
  <tbody>
    <tr><td>Under ~167 kg/CBM</td><td>Light and bulky</td><td>Air is billed on volume; expensive to fly. Sea strongly favoured.</td></tr>
    <tr><td>~167–500 kg/CBM</td><td>Moderate</td><td>Both modes worth quoting; run the numbers.</td></tr>
    <tr><td>Over ~500 kg/CBM</td><td>Dense</td><td>Air billed on actual weight; sea LCL billed on tonnage. Compare carefully.</td></tr>
    <tr><td>Over ~1000 kg/CBM</td><td>Very dense</td><td>Containers hit payload limits before filling. Watch road weight limits too.</td></tr>
  </tbody>
</table>
</div>

<p>The 167 kg/CBM figure is simply the point at which the ÷6000 air formula stops adding cost — 1,000,000 cm³ ÷ 6000 = 166.7 kg.</p>

<h2>Where this saves you money</h2>

<h3>Packaging redesign</h3>
<p>On low-density goods, freight can rival the goods cost. Ask the factory:</p>
<ul>
  <li>Can the product ship disassembled or nested?</li>
  <li>Can inner packaging be slimmed without failing a drop test?</li>
  <li>Can the carton be resized so more units fit in the same cube?</li>
  <li>Are there voids in the current carton that serve no purpose?</li>
</ul>
<p>A 15% reduction in cubic volume is a roughly 15% reduction in the freight line, on every shipment for the life of the product. That usually dwarfs whatever you could win by negotiating the unit price.</p>

<h3>Filling a container</h3>
<p>Once you are close to an FCL, the marginal cost of additional volume approaches zero. Knowing your CBM precisely tells you exactly how much more you could ship for effectively nothing.</p>

<h3>Checking the quote</h3>
<p>Calculate the CBM or chargeable weight yourself from the packing list and check it against the invoice. Re-measurement at the terminal is routine and adjustments are always upward — catching a discrepancy before booking is much easier than disputing it after.</p>

<div class="blog-callout warning">
  <p><strong>Use verified dimensions, not the supplier's estimate.</strong> Factories frequently quote nominal carton sizes that differ from what actually ships. Have carton dimensions and gross weights measured at the pre-shipment inspection — this is one of the concrete, immediately monetisable reasons to inspect.</p>
</div>

<h2>Quick reference</h2>

<ul>
  <li><strong>CBM:</strong> L(m) × W(m) × H(m), or L(cm) × W(cm) × H(cm) ÷ 1,000,000</li>
  <li><strong>Volumetric kg (air freight):</strong> L × W × H in cm ÷ 6000</li>
  <li><strong>Volumetric kg (express):</strong> L × W × H in cm ÷ 5000</li>
  <li><strong>Chargeable weight:</strong> the greater of actual and volumetric</li>
  <li><strong>Revenue tonne (LCL):</strong> the greater of CBM and tonnes</li>
  <li><strong>20 ft container:</strong> plan on ~25–28 CBM usable</li>
  <li><strong>40 ft container:</strong> plan on ~54–58 CBM usable</li>
  <li><strong>40 ft high cube:</strong> plan on ~60–68 CBM usable</li>
</ul>
""",
    },
    {
        'slug': 'paying-chinese-suppliers-safely',
        'title': 'Paying Chinese Suppliers Safely: T/T, L/C and Payment Terms That Protect You',
        'category': 'costs-payments',
        'excerpt': 'The payment schedule is your only real leverage. Structured properly it makes quality enforceable; structured badly it hands your money over before you have anything to inspect.',
        'meta_description': 'How to pay Chinese suppliers safely: T/T deposits, letters of credit, escrow, and the payment schedule that keeps leverage until after inspection.',
        'keywords': 'paying Chinese suppliers, T/T payment terms China, letter of credit import, 30/70 payment terms, supplier payment fraud',
        'body': """
<p>Most advice on paying Chinese suppliers focuses on which payment method to use. That matters less than <strong>when</strong> you pay. The schedule is the mechanism that makes everything else — your specification, your inspection, your contract — actually enforceable.</p>

<p>Once a supplier holds the full amount, your ability to get a defect fixed depends entirely on their goodwill.</p>

<h2>The standard structure, and why it works</h2>

<p>The conventional arrangement for a China order is <strong>30% deposit, 70% balance</strong>. What matters is the trigger for that balance:</p>

<div class="blog-table-wrap">
<table>
  <thead>
    <tr><th>Balance released</th><th>Your position</th></tr>
  </thead>
  <tbody>
    <tr><td>Before production ends</td><td>No leverage at all. Avoid.</td></tr>
    <tr><td>Against the bill of lading copy</td><td>Common, but goods have already shipped — you are inspecting after the fact.</td></tr>
    <tr><td><strong>After the inspection passes</strong></td><td><strong>The right structure.</strong> Defects are fixed while goods are still in the factory.</td></tr>
  </tbody>
</table>
</div>

<p>Write it explicitly: <em>"Balance payable within X days of a passed pre-shipment inspection conducted by [inspector] against AQL [level]. If the inspection fails, the supplier shall rework or replace at their cost and bear the cost of re-inspection."</em></p>

<p>A supplier who refuses this is telling you they are not confident of passing.</p>

<h2>The methods</h2>

<h3>T/T — telegraphic transfer</h3>
<p>An ordinary international bank transfer, and by far the most common method. Fast, cheap, universally accepted.</p>
<p><strong>The weakness:</strong> once sent, it is effectively irreversible. All of your protection has to come from the schedule and the contract, because the payment rail offers none.</p>

<h3>Letter of credit</h3>
<p>Your bank undertakes to pay the supplier's bank against presentation of specified documents. The bank checks the documents, not the goods.</p>
<p><strong>Strengths:</strong> the supplier cannot be paid without producing exactly the documents you specified — bill of lading, certificate of origin, inspection certificate. For a large first order with an unfamiliar supplier, that is real protection, and it protects both sides, which makes it easier to agree.</p>
<p><strong>Weaknesses:</strong> bank fees, administrative work, and strict document compliance — a discrepancy as small as a misspelling can stall payment and create its own dispute. It also verifies documents, not quality: a clean bill of lading says goods were loaded, not that they were good. Generally worth it above a significant order value, overkill below.</p>

<h3>Platform escrow (Alibaba Trade Assurance and similar)</h3>
<p>Funds are held by the platform and released on agreed conditions, with a dispute process behind it. Genuinely useful for smaller orders — provided you keep the entire transaction on the platform. Paying off-platform voids it completely, and being asked to do so is the most common way buyers lose this protection.</p>

<h3>Documentary collection (D/P, D/A)</h3>
<p>Documents are released through the banking system against payment or acceptance. Less common on this trade lane and offers less protection than an L/C. Rarely the right answer for a new relationship.</p>

<h3>Credit card and PayPal</h3>
<p>Occasionally available for samples and very small orders. Chargeback rights are a real protection, but fees are high and most factories will not accept them at volume. Fine for samples, not for production.</p>

<h2>The fraud that actually happens</h2>

<h3>Bank details changed by email</h3>
<p>The most costly and most common fraud on this route. A criminal compromises an email account — often the supplier's — and sends an invoice with altered bank details, usually at the moment a payment is expected.</p>

<div class="blog-callout warning">
  <p><strong>Rule:</strong> any change to bank details must be confirmed by voice, on a number you already held before the request arrived. Never on a number contained in the email requesting the change. Treat this as absolute — the money is not recoverable.</p>
</div>

<h3>Account name mismatch</h3>
<p>The beneficiary must be the exact company named on the contract and the business licence. Payments to a personal account, or to a differently-named entity, mean that if the deal goes wrong you have no documented transaction with the company you contracted with. There are legitimate reasons for an offshore payment entity, but it must be documented in the contract in advance.</p>

<h3>The vanishing deposit</h3>
<p>Deposit paid, then delays, then excuses, then silence. This is what supplier verification exists to prevent — see our <a href="/blog/how-to-verify-a-chinese-supplier/">supplier verification checklist</a>. It is very rare with a factory whose licence has been checked and whose building someone has stood in.</p>

<h3>Quality substitution after approval</h3>
<p>Sample approved, production runs with a cheaper material. Not a payment fraud as such, but the payment schedule is what protects you: caught at inspection, before the balance goes out, it is the supplier's problem.</p>

<h2>Practical measures</h2>

<ul>
  <li><strong>Keep the deposit proportionate.</strong> 30% is normal. A supplier demanding 50–100% upfront on a first order is asking you to carry all the risk.</li>
  <li><strong>Pay in one currency and agree who bears FX.</strong> USD is standard on this lane. Fix the currency in the contract.</li>
  <li><strong>Account for bank charges.</strong> Agree whether they are shared or borne by one side, or you will have a small argument about a short payment later.</li>
  <li><strong>Keep records.</strong> Contract, POs, invoices, transfer receipts, inspection reports, and the messaging history. If a dispute ever goes anywhere, this is the file.</li>
  <li><strong>Do not let terms drift.</strong> Suppliers often propose easier terms for themselves on the second and third order, once trust is established. Some of that is reasonable. Releasing the balance before inspection is not.</li>
</ul>

<h2>How terms should evolve</h2>

<p>Payment terms are part of the relationship. Order one, with a verified but unfamiliar factory: 30/70 against inspection, no exceptions. After several clean orders where you have paid promptly, a supplier may well offer better terms — a smaller deposit, or net terms after shipment. That is a real commercial benefit and worth earning.</p>

<p>What should not change is the inspection. Keep the checkpoint even when you no longer need the leverage, because the run where quality slips is exactly the run where nobody was watching.</p>
""",
    },
    {
        'slug': 'what-a-china-sourcing-agent-costs',
        'title': 'What a China Sourcing Agent Actually Costs — and How to Compare Quotes',
        'category': 'costs-payments',
        'featured': False,
        'excerpt': 'Commission, flat fee or hidden markup — the three ways sourcing is charged behave very differently as your order grows, and only one of them lets you check the factory price.',
        'meta_description': 'How China sourcing agents charge: commission on order value, flat fees per order, and hidden supplier markup. How to compare quotes and what should be included.',
        'keywords': 'China sourcing agent cost, sourcing agent commission, sourcing agent fees, how much does a sourcing agent charge, China buying agent pricing',
        'body': """
<p>Sourcing services are charged in one of three ways: a <strong>commission</strong> on order value, a <strong>flat fee</strong> per order or per month, or a <strong>hidden markup</strong> on the factory price. The first two are visible and comparable. The third is the one that costs you money you never see.</p>

<p>If you take one thing from this article: ask any agent, in writing, whether you will see the factory's actual invoice. The answer separates the models more reliably than the headline rate does.</p>

<h2>The three models</h2>

<h3>Commission on order value</h3>
<p>A percentage of the goods value, disclosed up front. You see the factory price and pay the agent's percentage on top. Typically in the mid single digits, lower on large orders and higher on small or complex ones.</p>
<p><strong>Where it works:</strong> you can verify what the factory charged, so the agent's incentive to find you a better price is not in conflict with their fee. <strong>Where it strains:</strong> on a very large order of a simple product, a percentage can exceed the work involved — which is why rates should taper with volume.</p>

<h3>Flat fee</h3>
<p>A fixed amount per order, or a monthly retainer. Predictable, and it decouples the fee from order value entirely.</p>
<p><strong>Where it works:</strong> high-value orders, or an ongoing programme with steady volume. <strong>Where it strains:</strong> a first small order, where a flat fee can be a large share of a modest purchase.</p>

<h3>Hidden markup</h3>
<p>The agent quotes you a delivered price and keeps the difference between that and what the factory charged. You never see the factory invoice.</p>
<p>You will often hear this described as "free" sourcing. It is not free; it is unpriced. The structural problem is not the margin itself but the incentive it creates: every saving the agent negotiates is theirs to keep, and there is no mechanism for you to find out. It also makes a genuine comparison between two suppliers impossible, because you are comparing two numbers that both contain an unknown.</p>

<div class="blog-callout">
  <p>A quoted percentage is not the whole cost, and the lowest percentage is not automatically the cheapest arrangement. What matters is the total delivered cost plus what happens when something goes wrong.</p>
</div>

<h2>What should be included</h2>

<p>Get this in writing before you engage anyone, because the gaps are where unexpected invoices come from:</p>

<div class="blog-table-wrap">
<table>
  <thead>
    <tr><th>Activity</th><th>Ask specifically</th></tr>
  </thead>
  <tbody>
    <tr><td>Supplier identification</td><td>How many candidates, and are they verified or just found?</td></tr>
    <tr><td>Factory verification</td><td>Business licence check, and is a site visit included?</td></tr>
    <tr><td>Quotation and negotiation</td><td>Included, or billed?</td></tr>
    <tr><td>Sample handling</td><td>Who pays for samples and the courier?</td></tr>
    <tr><td>Production follow-up</td><td>How often, and do you get a written update?</td></tr>
    <tr><td>Pre-shipment inspection</td><td>Included, or a separate line?</td></tr>
    <tr><td>Consolidation and warehousing</td><td>Free period, then what rate?</td></tr>
    <tr><td>Export documents</td><td>Who prepares them?</td></tr>
    <tr><td>Freight</td><td>Quoted separately or bundled? Can you see the carrier's rate?</td></tr>
    <tr><td>Claims and rework</td><td>Who chases the factory when a run is defective?</td></tr>
  </tbody>
</table>
</div>

<p>That last row is the one people skip and later care about most. When a shipment arrives wrong, the value of an agent is whether someone in the same country, in the same language, is pursuing the factory on your behalf. Establish before the order who that is.</p>

<h2>Comparing two quotes properly</h2>

<p>Put both on the same basis — total delivered cost for one realistic order:</p>

<ol>
  <li>Factory price for the actual quantity and specification</li>
  <li>Agent fee, however it is expressed</li>
  <li>Inspection, if charged separately</li>
  <li>Consolidation and handling</li>
  <li>Freight and insurance to your port</li>
  <li>Duty and VAT at destination</li>
  <li>Delivery to your warehouse</li>
</ol>

<p>Our <a href="/blog/how-to-calculate-landed-cost-china-to-uae/">landed cost guide</a> covers the calculation in full. Do it once per candidate and the comparison usually stops being close.</p>

<h2>Questions worth asking</h2>

<ul>
  <li><strong>Will I see the factory's invoice?</strong> The single most informative question in this article.</li>
  <li><strong>Are you taking any payment from the supplier?</strong> Commission from both sides is a genuine conflict of interest.</li>
  <li><strong>Who holds the supplier relationship?</strong> If the factory is never disclosed, you cannot leave.</li>
  <li><strong>What does your fee do if I reorder the same item?</strong> The work on order five is not the work on order one.</li>
  <li><strong>Where are you actually located?</strong> An agent in the same country as your factories can attend in person; one who is not is forwarding emails.</li>
</ul>

<h2>When you do not need an agent</h2>

<p>Honest answer: if you are ordering a simple, unregulated product from a supplier you have already used successfully, and you are comfortable managing payment and freight, you may not need one. The case for an agent is strongest with a new supplier, a regulated product, a first order in a new market, or quality problems you cannot resolve from a distance. See <a href="/blog/what-is-a-china-sourcing-agent/">what a sourcing agent does</a> and <a href="/blog/alibaba-vs-sourcing-agent/">Alibaba vs a sourcing agent</a>.</p>

<div class="blog-callout">
  <p>We work on a disclosed commission and you see the factory invoice — you always know the goods price and what our part costs. <a href="/contact/">Tell us what you are looking to buy</a> and we will quote the rate for your product and volume before any commitment.</p>
</div>
""",
    },
]
