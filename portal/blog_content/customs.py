"""Blog articles: UAE customs, duty, VAT, documentation and product compliance."""

CATEGORY = {
    'name': 'Customs & Compliance',
    'slug': 'customs-compliance',
    'description': 'Duty, VAT, documentation and the approvals your goods need to clear into the UAE.',
    'display_order': 3,
}

POSTS = [
    {
        'slug': 'uae-customs-duty-and-vat-on-imports-from-china',
        'title': 'UAE Customs Duty and VAT on Imports from China: How It Works',
        'category': 'customs-compliance',
        'featured': True,
        'excerpt': 'Duty is charged on the CIF value, VAT is charged on the value plus the duty, and the order of that calculation surprises a lot of first-time importers.',
        'meta_description': 'How UAE customs duty and 5% VAT are calculated on imports from China, what the CIF value includes, which goods are exempt, and how free zones change the picture.',
        'keywords': 'UAE customs duty China imports, UAE import VAT, GCC common external tariff, customs duty Dubai, CIF value customs UAE',
        'body': """
<p>Two separate charges apply when goods arrive in the UAE from China: <strong>customs duty</strong> and <strong>VAT</strong>. They are calculated on different bases, and VAT is applied <em>after</em> duty — so duty increases your VAT bill as well.</p>

<div class="blog-callout warning">
  <p>Rates, exemptions and procedures change. This article explains the structure so you can plan and budget; always confirm the current position for your specific goods with UAE Customs, the Federal Tax Authority or your customs broker before you commit to an order.</p>
</div>

<h2>Customs duty</h2>

<p>The UAE applies the <strong>GCC Common External Tariff</strong>. The standard rate for most goods is <strong>5%</strong>, charged on the CIF value.</p>

<p>Outside that standard rate:</p>

<ul>
  <li>A number of categories are <strong>duty-exempt</strong> — many basic foodstuffs, pharmaceuticals, and certain agricultural and industrial inputs.</li>
  <li>Some goods carry <strong>higher rates</strong>. Tobacco and alcohol are the notable ones and are treated very differently.</li>
  <li><strong>Excise tax</strong> applies separately to specific categories — tobacco products, energy drinks, carbonated drinks and certain sweetened beverages — at substantial rates, and it is calculated in addition to duty and VAT.</li>
</ul>

<p>Your actual rate depends on the <strong>HS code</strong> of the product. Getting that code right matters more than most importers realise: it determines the duty rate, whether any exemption applies, and which regulatory approvals are triggered. An incorrect classification can mean underpayment (a compliance problem) or overpayment (money you will not easily get back).</p>

<h2>What "CIF value" actually includes</h2>

<p>Duty is charged on the CIF value, which is <strong>not</strong> just what you paid the supplier:</p>

<blockquote><p>CIF value = Cost of goods + Insurance + Freight to the UAE port</p></blockquote>

<p>This catches out importers who buy FOB and budget duty against the invoice value alone. If you paid USD 20,000 for goods and USD 3,000 for freight and insurance, duty is assessed on USD 23,000, not USD 20,000.</p>

<h2>VAT</h2>

<p>The UAE standard VAT rate is <strong>5%</strong>, and import VAT is charged on the <strong>duty-inclusive</strong> value:</p>

<blockquote><p>Import VAT = (CIF value + customs duty + any excise) × 5%</p></blockquote>

<p>If your business is <strong>VAT-registered in the UAE</strong>, import VAT is generally recoverable as input tax, subject to the normal rules and provided you hold proper documentation and the import is correctly recorded against your registration. Registered importers commonly account for import VAT through the VAT return rather than paying it in cash at the border.</p>

<p>If you are <strong>not VAT-registered</strong>, the VAT is a real cost that has to sit in your landed-cost calculation.</p>

<div class="blog-callout">
  <p><strong>This is a concrete reason to keep control of your customs entry.</strong> If a supplier ships DDP and the goods are cleared under someone else's arrangement, you may not end up with the documentation that supports recovering that import VAT. See our guide to <a href="/blog/incoterms-explained-for-uae-importers/">Incoterms for UAE importers</a>.</p>
</div>

<h2>A worked example</h2>

<p>Assume a standard-rated product, 5% duty, and a VAT-registered importer:</p>

<div class="blog-table-wrap">
<table>
  <thead>
    <tr><th>Line</th><th>Amount (USD)</th><th>How it is derived</th></tr>
  </thead>
  <tbody>
    <tr><td>Goods (FOB China)</td><td>20,000</td><td>Supplier invoice</td></tr>
    <tr><td>Sea freight</td><td>2,600</td><td>Forwarder invoice</td></tr>
    <tr><td>Insurance</td><td>150</td><td>Policy</td></tr>
    <tr><td><strong>CIF value</strong></td><td><strong>22,750</strong></td><td>Goods + freight + insurance</td></tr>
    <tr><td>Customs duty @ 5%</td><td>1,137.50</td><td>5% of CIF</td></tr>
    <tr><td>Value for VAT</td><td>23,887.50</td><td>CIF + duty</td></tr>
    <tr><td>Import VAT @ 5%</td><td>1,194.38</td><td>5% of the above</td></tr>
    <tr><td><strong>Cash at import</strong></td><td><strong>2,331.88</strong></td><td>Duty + VAT</td></tr>
    <tr><td><strong>Net cost if VAT-registered</strong></td><td><strong>1,137.50</strong></td><td>Duty only; VAT recovered</td></tr>
  </tbody>
</table>
</div>

<p>Note the difference between the last two rows. A registered business budgets duty as cost and VAT as cash flow. An unregistered one budgets both as cost — a material difference on a thin-margin product.</p>

<h2>Free zones change the timing</h2>

<p>Goods brought into a UAE free zone are generally not subject to import duty at the point of entry. Duty becomes payable when the goods move out of the free zone into the mainland.</p>

<p>The practical implications:</p>

<ul>
  <li><strong>Re-export.</strong> Goods that arrive, are stored in a free zone and then leave the country generally do not attract UAE import duty at all. If you supply the wider GCC, Africa or the CIS from a UAE base, this is significant.</li>
  <li><strong>Cash flow.</strong> Duty is deferred until you actually move stock to the mainland, rather than paid on the whole container at arrival.</li>
  <li><strong>Selling into the mainland</strong> from a free-zone entity carries its own licensing considerations and typically involves a mainland distributor.</li>
</ul>

<h2>Rules of origin</h2>

<p>Duty depends on where goods <strong>originate</strong>, not where they were shipped from. Goods of GCC origin move duty-free within the GCC. Various preferential arrangements exist with other countries and change over time.</p>

<p>For Chinese-origin goods you will normally need a <strong>certificate of origin</strong>, issued in China and typically attested as required. Get this organised with the supplier before shipment — chasing it after the container has arrived is a classic cause of demurrage.</p>

<h2>Under-declaration: why it is not worth it</h2>

<p>Some Chinese suppliers offer to declare a lower value to reduce your duty. Understand what is being proposed: it is customs fraud, and the liability sits with the <strong>importer of record</strong> — you.</p>

<p>Beyond the legal exposure, there are practical costs. Customs authorities maintain valuation databases and query prices that fall outside expected ranges; a query means physical inspection and delay while demurrage accrues. Your cargo insurance pays out against declared value, so an under-declared shipment that is lost or damaged is under-insured. And if you are VAT-registered, your import records will not reconcile with what you actually paid your supplier.</p>

<p>On standard-rated goods, the duty saved is 5%. The exposure is not proportionate.</p>

<h2>Planning checklist</h2>

<ul>
  <li>Identify the correct HS code before you order — it drives duty, exemptions and approvals.</li>
  <li>Budget duty on the <strong>CIF</strong> value, not the goods value.</li>
  <li>Budget VAT on <strong>CIF plus duty</strong>.</li>
  <li>Check whether excise applies to your category.</li>
  <li>Decide free zone versus mainland before shipping.</li>
  <li>Arrange the certificate of origin with the supplier at order stage.</li>
  <li>Confirm current rates with your broker — this article describes the structure, not today's tariff schedule.</li>
</ul>
""",
    },
    {
        'slug': 'documents-needed-to-import-from-china-to-uae',
        'title': 'Documents You Need to Import from China to the UAE',
        'category': 'customs-compliance',
        'excerpt': 'Missing paperwork is the most common reason a container sits at Jebel Ali accruing demurrage. Here is the full set, what each one must contain, and who produces it.',
        'meta_description': 'The complete document set for importing from China to the UAE: commercial invoice, packing list, bill of lading, certificate of origin and conformity certificates.',
        'keywords': 'import documents UAE, commercial invoice requirements, certificate of origin China, bill of lading, packing list requirements UAE customs',
        'body': """
<p>Almost every expensive delay at Jebel Ali traces back to a document that was wrong, late or missing. The goods are fine, the duty is payable, and the container sits in the terminal accruing charges because a certificate of origin was never requested.</p>

<p>The fix is unglamorous: agree the full document set with your supplier at order stage, and check each one the day it is issued rather than the day the vessel berths.</p>

<h2>Commercial invoice</h2>

<p><strong>Produced by:</strong> the supplier.</p>

<p>The core customs document. It must show:</p>

<ul>
  <li>Full legal name and address of both seller and buyer — the buyer must match your trade licence exactly</li>
  <li>Invoice number and date</li>
  <li>Clear description of the goods (not just a model number — customs need to know what it is)</li>
  <li>HS code for each line</li>
  <li>Quantity, unit price and line total</li>
  <li>Currency</li>
  <li><strong>The Incoterm, with named place</strong> — e.g. "FOB Ningbo"</li>
  <li>Country of origin</li>
  <li>Freight and insurance shown separately if the term includes them</li>
</ul>

<div class="blog-callout warning">
  <p><strong>The most common error:</strong> a consignee name on the invoice that does not exactly match the trade licence. "Al Noor Trading" versus "Al Noor Trading LLC" is enough to hold a shipment. Send your supplier your exact legal name in writing and check every document against it.</p>
</div>

<h2>Packing list</h2>

<p><strong>Produced by:</strong> the supplier.</p>

<p>Must correspond line for line with the commercial invoice, and add:</p>

<ul>
  <li>Number of cartons or pallets, with carton numbering</li>
  <li>Contents and quantity per carton</li>
  <li>Net and gross weight per carton and in total</li>
  <li>Carton dimensions and total CBM</li>
  <li>Shipping marks</li>
</ul>

<p>The dimensions and weights here are also what your freight is billed against, so verify them at inspection rather than accepting the supplier's estimate.</p>

<h2>Bill of lading (sea) or air waybill (air)</h2>

<p><strong>Produced by:</strong> the carrier or forwarder.</p>

<p>The contract of carriage and, for a sea shipment, the document of title — whoever holds the original bill of lading controls the goods. Check on the day it is issued:</p>

<ul>
  <li>Consignee name and address, exactly correct</li>
  <li>Notify party — usually you and/or your clearing agent</li>
  <li>Port of loading and discharge</li>
  <li>Container and seal numbers</li>
  <li>Description, marks, weights matching the packing list</li>
  <li>Freight prepaid or freight collect, matching your Incoterm</li>
</ul>

<p>Amending a bill of lading after issue takes days and sometimes a fee. Amending it after the vessel has sailed is worse.</p>

<h3>Original versus telex release</h3>
<p>With an original bill of lading, the physical document must reach you and be surrendered at destination — which means couriering paper from China and is a genuine cause of delay. A <strong>telex release</strong> (or a sea waybill) lets the carrier release the goods without the physical original. Agree which you are using before shipment; the choice usually depends on your payment terms and how much you trust the counterparty.</p>

<h2>Certificate of origin</h2>

<p><strong>Produced by:</strong> the supplier, issued by a Chinese authority such as the CCPIT or a chamber of commerce.</p>

<p>States where the goods were manufactured. Required for customs clearance and for determining whether any preferential duty rate applies. Depending on the goods and current requirements, it may need to be attested — confirm with your broker what your consignment needs, because requirements vary.</p>

<p>This is the single most commonly forgotten document. Request it at order stage, in writing, as a condition of the final payment.</p>

<h2>Conformity and product-specific certificates</h2>

<p><strong>Produced by:</strong> the supplier and/or an accredited certification body.</p>

<p>What you need depends entirely on the product. Categories that commonly require approval before they can be sold or cleared in the UAE include electrical goods, toys, cosmetics, food contact materials, food and beverages, medical devices, chemicals, and telecommunications equipment.</p>

<p>The UAE conformity framework includes ECAS (Emirates Conformity Assessment Scheme), the Emirates Quality Mark, and the Gulf-wide G-Mark for certain regulated products, administered by the relevant UAE authority. Halal certification applies to food and some other categories.</p>

<div class="blog-callout warning">
  <p><strong>Establish certification requirements before you place the order, not before you ship.</strong> Certification often has to be built into the product and its labelling. Discovering at the port that your goods need approval they do not have leaves you with a container you cannot clear.</p>
</div>

<h2>Insurance certificate</h2>

<p><strong>Produced by:</strong> whoever arranged the cover — you, under FOB; the supplier, under CIF.</p>

<p>Needed for the customs valuation if insurance is part of the CIF value, and needed by you if anything goes wrong. Note that the minimum cover required under CIF is basic; for valuable cargo, arrange your own policy at a level that actually reflects the loss.</p>

<h2>Your own registrations</h2>

<ul>
  <li><strong>Valid UAE trade licence</strong> covering the activity of importing these goods</li>
  <li><strong>Customs importer code</strong>, registered with the relevant customs authority</li>
  <li><strong>VAT registration</strong> (TRN) if applicable — needed to account for and recover import VAT</li>
</ul>

<h2>Delivery order</h2>

<p><strong>Produced by:</strong> the carrier at destination.</p>

<p>Issued once freight and charges are settled and the bill of lading is surrendered or telex-released. Without it the terminal will not release the container, regardless of your customs status.</p>

<h2>A practical routine</h2>

<ol>
  <li><strong>At order:</strong> send the supplier your exact legal name, address, trade licence number and TRN. List every document you require as a condition of final payment.</li>
  <li><strong>At inspection:</strong> verify carton counts, dimensions and weights so the packing list is accurate before it is finalised.</li>
  <li><strong>At shipment:</strong> get draft copies of every document and check them before they are issued in final form. This is the moment when corrections are cheap.</li>
  <li><strong>While in transit:</strong> send the full set to your clearing agent so the entry can be pre-filed and clearance starts the day the vessel berths.</li>
</ol>
""",
    },
    {
        'slug': 'uae-free-zone-vs-mainland-for-importers',
        'title': 'UAE Free Zone vs Mainland: Which Suits Your Import Business?',
        'category': 'customs-compliance',
        'excerpt': 'The structure you import under changes when you pay duty, who you can sell to, and how much of a re-export business is viable. It is worth deciding deliberately.',
        'meta_description': 'Free zone versus mainland for UAE importers: how duty deferral, re-export, market access and ownership differ, and which structure suits which business model.',
        'keywords': 'UAE free zone vs mainland, JAFZA import, re-export UAE, free zone duty deferral, Dubai import company setup',
        'body': """
<p>Where your company is licensed determines when you pay customs duty, who you are allowed to sell to, and whether a re-export business is economically sensible. For an importer these are not administrative details — they are the shape of the business.</p>

<div class="blog-callout warning">
  <p>Company structure, licensing and tax are areas where the rules are detailed and change. This article outlines the trade-offs so you can ask the right questions; take advice from a licensed corporate services adviser and your tax adviser before deciding.</p>
</div>

<h2>What a free zone is</h2>

<p>A UAE free zone is a designated area with its own licensing authority. For customs purposes, designated zones sit outside the UAE customs territory: goods can be brought in, stored, and taken out again without import duty being paid on entry.</p>

<p>The UAE has many, and importers most often encounter <strong>JAFZA</strong> (adjacent to Jebel Ali Port), <strong>DAFZA</strong> (at Dubai airport), the <strong>Sharjah</strong> zones, and <strong>KIZAD</strong> in Abu Dhabi. Which is right depends heavily on where your goods physically arrive and where they go next.</p>

<h2>Duty: the core difference</h2>

<h3>Free zone</h3>
<ul>
  <li>No import duty on goods entering the zone.</li>
  <li>Duty becomes payable when goods move from the zone into the UAE mainland.</li>
  <li>Goods re-exported out of the country generally do not attract UAE import duty at all.</li>
</ul>

<h3>Mainland</h3>
<ul>
  <li>Duty and VAT settled at import, on the whole consignment.</li>
</ul>

<p>Two consequences follow. First, <strong>cash flow</strong>: a free-zone importer pays duty as stock is released to the local market, rather than on the entire container at arrival. On a large shipment sold over months, that matters. Second, <strong>re-export economics</strong>: if a meaningful share of your goods leaves the country again, paying UAE import duty on them makes no sense, and the free-zone route is often the difference between a viable regional distribution business and an uncompetitive one.</p>

<h2>Market access: the other core difference</h2>

<p>A free-zone company generally cannot sell directly into the UAE mainland market in the way a mainland company can. Selling locally is typically handled through a mainland distributor or agent, or by establishing a mainland presence. That arrangement adds a layer of cost and a partner relationship to manage.</p>

<p>A mainland company sells into the local market without that constraint, and can more readily do business with government entities.</p>

<h2>Which suits which business</h2>

<div class="blog-table-wrap">
<table>
  <thead>
    <tr><th>Your business</th><th>Usually points to</th></tr>
  </thead>
  <tbody>
    <tr><td>Selling to UAE retailers, businesses and consumers</td><td>Mainland</td></tr>
    <tr><td>Distributing across the GCC, Africa or CIS from a UAE hub</td><td>Free zone</td></tr>
    <tr><td>Mixed — some local sales, substantial re-export</td><td>Often both, or free zone plus a mainland distributor</td></tr>
    <tr><td>Storing and consolidating before onward shipment</td><td>Free zone</td></tr>
    <tr><td>Marketplace selling on Amazon.ae or Noon</td><td>Depends on the fulfilment model — check where the platform requires stock to sit and who is importer of record</td></tr>
    <tr><td>Bidding for government contracts</td><td>Mainland</td></tr>
  </tbody>
</table>
</div>

<h2>Other factors worth weighing</h2>

<h3>Setup and running cost</h3>
<p>Free zones package licence, visas and often premises, with cost varying widely between zones. Mainland setup has its own cost structure. Neither is universally cheaper — compare on your actual requirements, particularly the number of visas and the amount of warehouse space you need.</p>

<h3>Warehousing</h3>
<p>If you need bonded storage adjacent to the port, a free zone at Jebel Ali is hard to beat on logistics. If your warehouse is inland, the free-zone advantage shrinks once you add trucking.</p>

<h3>VAT</h3>
<p>Some free zones are "designated zones" for VAT purposes, which changes how supplies are treated. This is genuinely technical and depends on the specific zone and transaction — it is the part most worth taking professional advice on.</p>

<h3>Corporate tax</h3>
<p>The UAE has a corporate tax regime, with particular treatment available to qualifying free-zone persons meeting defined conditions. The conditions are specific and worth understanding properly before assuming a benefit applies.</p>

<h2>Questions to answer before you decide</h2>

<ol>
  <li>What proportion of goods will be sold in the UAE versus re-exported? This single answer drives most of the decision.</li>
  <li>Who are your customers — mainland businesses, consumers, government, or overseas buyers?</li>
  <li>Where will the goods physically arrive, and where must they be stored?</li>
  <li>How many visas do you need?</li>
  <li>Does your product category carry regulatory approval requirements that differ by structure?</li>
  <li>What is your expected duty exposure per year — enough that deferral or exemption is material?</li>
</ol>

<p>Answer those honestly and the structure usually becomes obvious. Where it does not, it is generally because the business genuinely spans both models, in which case a combined arrangement is worth costing rather than forcing a single answer.</p>
""",
    },
    {
        'slug': 'product-certification-for-uae-imports',
        'title': 'Product Certification for UAE Imports: What Your Goods Need',
        'category': 'customs-compliance',
        'excerpt': 'Certification has to be designed into the product, not added at the port. Finding out at Jebel Ali that your goods need approval they do not have is the worst possible time.',
        'meta_description': 'Which imported products need UAE conformity approval, how ECAS, EQM and G-Mark work, and how to build certification into a China order from the start.',
        'keywords': 'ECAS certification UAE, G-Mark, Emirates Quality Mark, UAE product certification import, MOIAT conformity',
        'body': """
<p>Certification is the requirement that most often turns a profitable import into a stranded container. Unlike duty — which is a cost you can pay — a missing conformity approval can mean goods that cannot legally be cleared or sold, and that must be re-exported or destroyed.</p>

<p>The reason it catches people is timing. Certification usually has to be built into the product and its labelling during manufacture. By the time the goods reach Jebel Ali, the opportunity to comply has passed.</p>

<div class="blog-callout warning">
  <p>Requirements are product-specific and change. This article explains the framework and the process; confirm what applies to your exact goods with the relevant UAE authority or a licensed conformity assessment body before you place an order.</p>
</div>

<h2>The UAE framework, in outline</h2>

<h3>ECAS — Emirates Conformity Assessment Scheme</h3>
<p>The mandatory scheme for regulated product categories. It results in a Certificate of Conformity for the product, based on test reports and technical documentation demonstrating that the product meets the applicable UAE or GCC standard.</p>

<h3>EQM — Emirates Quality Mark</h3>
<p>A voluntary mark indicating compliance with the relevant standard plus assessment of the manufacturer's quality system. Mandatory for a small number of categories, and commercially valuable in others — some buyers and tenders require it.</p>

<h3>G-Mark — Gulf Conformity Mark</h3>
<p>A GCC-wide mark applied to certain regulated categories, notably low-voltage electrical equipment and toys. Goods in scope must carry the mark and be supported by the required technical file and declaration of conformity.</p>

<h3>Sector-specific regimes</h3>
<p>Food, medicines, medical devices, cosmetics, telecommunications equipment and chemicals each sit under their own regulatory authority with its own registration and approval process, in addition to or instead of the general conformity schemes.</p>

<h2>Categories that commonly need approval</h2>

<ul>
  <li><strong>Electrical and electronic goods</strong> — appliances, lighting, chargers, power supplies, anything mains-connected</li>
  <li><strong>Toys and children's products</strong> — safety and materials requirements, often the strictest category</li>
  <li><strong>Cosmetics and personal care</strong> — product registration and ingredient compliance</li>
  <li><strong>Food, beverages and food-contact materials</strong> — including labelling, shelf life and halal requirements where applicable</li>
  <li><strong>Medical devices and supplements</strong></li>
  <li><strong>Automotive parts</strong>, particularly safety-critical components and tyres</li>
  <li><strong>Building and construction materials</strong></li>
  <li><strong>Telecommunications and radio equipment</strong> — type approval for anything transmitting</li>
  <li><strong>Chemicals, detergents and paints</strong></li>
</ul>

<p>If your product is not obviously in one of these groups, do not assume it is unregulated — check the HS code against the regulated list. Plenty of ordinary consumer goods sit inside scope in ways that are not intuitive.</p>

<h2>Getting it right on a China order</h2>

<h3>1. Determine the requirement before you order</h3>
<p>Identify the HS code, then establish which schemes and standards apply. Do this before the specification is finalised, because compliance often dictates components — a particular plug type, a specific plastic grade, a battery protection circuit.</p>

<h3>2. Ask what the supplier already holds</h3>
<p>Many Chinese factories exporting to the Gulf already have certification for their standard products. Ask specifically:</p>
<ul>
  <li>Which certificates do you hold for this exact model?</li>
  <li>Which body issued them and when do they expire?</li>
  <li>Are they in the name of <em>this</em> company, or a related one?</li>
</ul>

<div class="blog-callout">
  <p><strong>Verify certificates independently.</strong> Forged and expired certificates circulate. Check the certificate number with the issuing body. A supplier who is offended by this is not a supplier you want on a regulated product.</p>
</div>

<h3>3. Understand what the certificate covers</h3>
<p>A certificate is issued for a specific model, with a specific specification, from a specific factory. If you change the housing colour that is usually fine; if you change the power supply, the battery chemistry or the material, it may not be. Ask before you customise.</p>

<p>Watch particularly for CE marking being offered as a substitute. CE is a European mark. It may mean the product was tested against standards that overlap with the UAE requirement, which helps, but it is not itself UAE conformity.</p>

<h3>4. Build labelling into the order</h3>
<p>Labelling requirements are part of compliance and are frequently what fails. Depending on the product, that can include the conformity mark itself, country of origin, importer details, Arabic-language content, ingredient or material declarations, and safety warnings.</p>

<p>Labelling is applied during production. Getting it wrong means relabelling an entire consignment — sometimes possible in a bonded warehouse, always expensive, occasionally not permitted at all.</p>

<h3>5. Verify at inspection</h3>
<p>Include certification and labelling in the pre-shipment inspection scope: the mark is present, correctly applied, on the right surface; the label content matches the requirement; the documentation pack is complete. This is the last checkpoint where a problem is still the supplier's to fix.</p>

<h2>Who can hold the certification</h2>

<p>Depending on the scheme, the certificate holder may be the manufacturer or the UAE importer. This matters commercially: if certification is held in your name, you control it and can change factory without recertifying from scratch. If it is held by the supplier, switching suppliers means starting again — which is a form of lock-in worth being aware of when you negotiate.</p>

<h2>Budgeting for it</h2>

<p>Certification costs money and, more importantly, takes time — testing, documentation and issuance can run to several weeks. Build it into the project timeline at the start. On a first order for a regulated product, certification is frequently the longest lead item, longer than production itself.</p>

<p>It is also a barrier to entry working in your favour: competitors who cannot be bothered to certify properly are competitors who cannot legally sell.</p>
""",
    },
]
