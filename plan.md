# LogiManager Portal Redesign Plan

## Objective
Completely redesign the public-facing customer portal of LogiManager (China Sourcing Agent for UAE/Middle East) with a warm, professional, China-inspired design system.

## Design Tokens
- **Primary**: #C84B31 (terracotta red)
- **Secondary**: #2D5A27 (deep green)
- **Accent**: #F5A623 (gold)
- **Dark bg**: #0F172A (slate)
- **Text**: #1E293B (dark slate), #64748B (muted), #F8FAFC (light)
- **No blue/purple gradients** — warm, low-saturation tones only

## Stage 1: CSS Foundation
Rewrite `static/portal.css` entirely with new design system.

## Stage 2: Landing Page
Rewrite `portal/templates/portal/front_page.html` with full-viewport hero, trust bar, services grid, about section, portfolio, testimonials, CTA.

## Stage 3: Content Pages
Rewrite about.html, services.html, contact.html with new layouts.

## Stage 4: Info Pages
Rewrite faq.html, testimonials.html, portfolio.html with new layouts.

## Stage 5: Auth Pages
Rewrite login.html, register.html, forgot_password.html, reset_password.html with modern split-panel auth layouts. Preserve all AJAX functionality.

## Stage 6: Portal Pages
Rewrite dashboard.html, orders.html, order_detail.html, products.html, profile.html, ledger.html, request_quote.html, my_requests.html with modern dashboard layouts.

## Stage 7: Verification
Test server at http://127.0.0.1:8000/ and verify pages load.
