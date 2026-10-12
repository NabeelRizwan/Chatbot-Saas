"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpenCheck, Check, ChevronDown, FileText, Globe2, Layers3, Menu, MessageSquare, MessagesSquare, Palette, PanelTop, ShieldCheck, SlidersHorizontal, UsersRound, X } from "lucide-react";
import { BrandMark } from "@/components/brand/brand-mark";
import { useMounted } from "@/hooks/use-mounted";
import styles from "./landing.module.css";

const previews = [
  { label: "Product questions", question: "Help me find the right product.", answer: "Turn the information on your product pages into a helpful conversation. Visitors can ask about details, compare options and open the relevant product page.", tag: "Answers from your content", icon: BookOpenCheck },
  { label: "Contact requests", question: "Can someone help with my project?", answer: "Give visitors a simple way to leave their name, email and a message. Your team can review their request in one place and follow up.", tag: "Contact form with consent", icon: UsersRound },
  { label: "Next steps", question: "I'd like to book a consultation.", answer: "Connect your existing scheduling page so visitors can choose a time. For store customers, add a link to their secure order account.", tag: "Your booking or order page", icon: ArrowUpRight },
] as const;

const features = [
  { icon: Globe2, title: "Your knowledge, in reach.", text: "Connect website pages and upload documents. Keep the information behind your answers organized and easy to update." },
  { icon: Palette, title: "A natural part of your brand.", text: "Set your welcome message, colors, layout and appearance. Embed your chat on a website or share a standalone link." },
  { icon: BookOpenCheck, title: "A say in what gets said.", text: "Write and approve answers for recurring questions. Link them to sources so changes can be reviewed." },
  { icon: UsersRound, title: "Conversations with a next step.", text: "Collect contact requests, show relevant product cards, and direct visitors to booking or customer account pages." },
  { icon: MessagesSquare, title: "A clearer view of your customers.", text: "Review conversations, explore common questions and see where your chatbot needs more information." },
  { icon: SlidersHorizontal, title: "Room to test and improve.", text: "Save real customer questions, run them against your bot and compare actual answers with your expected facts." },
] as const;

const questions = [
  { question: "Where do the answers come from?", answer: "Your chatbot uses the website pages and documents you connect to its knowledge base. You can also add reviewed FAQ answers for specific questions and their explicit alternative wordings. AI-generated replies should still be tested and reviewed for your use case." },
  { question: "Can I use it without a website?", answer: "Yes. Enable customer experience features and the standalone chat link in your bot's settings, then make the bot active. You can share the link directly without installing a widget on a website." },
  { question: "Can I choose how the widget looks?", answer: "Yes. Customize its colors, welcome message, launcher, position, theme, type style, spacing and corners. Preview your changes before sharing it with visitors." },
  { question: "Do I have to move my booking or store system?", answer: "No. You can link your existing public booking page or secure customer order page. Visitors finish booking or sign in to view orders with that provider; the chatbot does not independently make bookings or look up private orders." },
  { question: "Can I use my own AI provider?", answer: "Your bot has provider and model settings, with options for your own API credentials or credentials supplied through the platform. Provider availability, usage charges and limits depend on your configuration." },
] as const;

export function LandingPage() {
  const mounted = useMounted();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const [preview, setPreview] = useState(0);
  const activePreview = previews[preview];
  const PreviewIcon = activePreview.icon;

  return <div className={styles.page}>
    <a className={styles.skip} href="#main-content">Skip to content</a>
    <header className={styles.header} onKeyDown={(event) => { if (event.key === "Escape" && menuOpen) { setMenuOpen(false); menuButton.current?.focus(); } }}>
      <div className={styles.navbar}>
        <Link href="/" className={styles.brand} aria-label="Chatbot SaaS home"><span className={styles.brandMark}><BrandMark size={34} /></span>Chatbot SaaS</Link>
        <nav className={styles.desktopNav} aria-label="Main navigation"><a href="#experience">The experience</a><a href="#how-it-works">How it works</a><a href="#questions">Questions</a></nav>
        <div className={styles.navActions}><Link href="/login" className={styles.signIn}>Sign in</Link><Link href="/signup" className={styles.navCta}>Get started<ArrowUpRight size={16} /></Link><button ref={menuButton} disabled={!mounted} className={styles.menuButton} aria-label={menuOpen ? "Close menu" : "Open menu"} aria-expanded={menuOpen} aria-controls="landing-mobile-nav" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={22} /> : <Menu size={22} />}</button></div>
      </div>
      {menuOpen && <nav id="landing-mobile-nav" className={styles.mobileNav} aria-label="Mobile navigation"><a href="#experience" onClick={() => setMenuOpen(false)}>The experience</a><a href="#how-it-works" onClick={() => setMenuOpen(false)}>How it works</a><a href="#questions" onClick={() => setMenuOpen(false)}>Questions</a><Link href="/login">Sign in to your workspace</Link></nav>}
    </header>

    <main id="main-content" tabIndex={-1}>
      <section className={styles.hero} aria-labelledby="hero-title">
        <div className={styles.heroCopy}><p className={styles.eyebrow}><span />YOUR KNOWLEDGE. A CLOSER CONNECTION.</p><h1 id="hero-title">Your website knows a lot.<br /><span>Let it talk.</span></h1><p className={styles.heroDescription}>Everything your business knows.<br className={styles.desktopBreak} /> One beautifully simple conversation.</p><div className={styles.heroActions}><Link href="/signup" className={styles.primaryButton}>Build your chatbot<ArrowUpRight size={18} /></Link><a href="#experience" className={styles.textLink}>Take a closer look<ArrowDown size={16} /></a></div><div className={styles.heroNotes}><span><Check size={13} />Your content</span><span><Check size={13} />Your brand</span><span><Check size={13} />Your choice of AI</span></div></div>
        <div className={styles.showcase}>
          <div className={styles.windowBar}><div aria-hidden="true" className={styles.windowDots}><i /><i /><i /></div><span>Your assistant workspace</span><span className={styles.windowLabel}>Illustrative preview</span></div>
          <div className={styles.showcaseBody}>
          <div className={styles.knowledgePreview}>
            <span className={styles.workspaceBadge}><Layers3 size={15} />Built around your business</span>
            <h2>A world of knowledge.<br /><span>Ready for a question.</span></h2>
            <p>Your pages, your documents, your expertise. Brought together in a conversation that feels natural.</p>
            <div className={styles.sourceList}>
              <div><span><Globe2 size={19} /></span><div><strong>Website pages</strong><small>Your products and services</small></div><Check size={15} /></div>
              <div><span><FileText size={19} /></span><div><strong>Documents</strong><small>Guides, details and policies</small></div><Check size={15} /></div>
              <div><span><BookOpenCheck size={19} /></span><div><strong>Approved answers</strong><small>The words you have reviewed</small></div><Check size={15} /></div>
            </div>
            <div className={styles.knowledgeFoot}><ShieldCheck size={16} /><span>Your knowledge. Your control.</span></div>
          </div>
          <div className={styles.heroVisual}>
          <div className={styles.visualTop}><span><span className={styles.smallDot} />A little closer to your customers</span><span className={styles.previewLabel}>ILLUSTRATIVE PREVIEW</span></div>
          <div className={styles.previewTabs} aria-label="Preview conversation types">{previews.map((item, index) => <button disabled={!mounted} key={item.label} aria-pressed={preview === index} onClick={() => setPreview(index)}>{item.label}</button>)}</div>
          <figure className={styles.chatPreview}>
            <figcaption className={styles.chatHeader}><span className={styles.chatAvatar}><BrandMark size={25} /></span><span><strong>Your brand assistant</strong><small>Here to help you explore</small></span><span className={styles.previewPill}>Preview</span></figcaption>
            <div className={styles.chatBody} aria-live="polite"><div className={styles.visitorBubble}>{activePreview.question}</div><div className={styles.replyLabel}><span /><strong>YOUR ASSISTANT</strong></div><p className={styles.assistantReply}>{activePreview.answer}</p><div className={styles.evidenceTag}><PreviewIcon size={14} />{activePreview.tag}</div></div>
            <div className={styles.previewBottom}><span>Make it yours.</span><Link href="/signup" aria-label="Create your own chatbot">Start building<ArrowRight size={17} /></Link></div>
          </figure>
          <div className={styles.sourceStrip}><span className={styles.smallDot} /><p>Designed to feel like part of your business.</p></div>
          </div>
          </div>
        </div>
      </section>

      <section className={styles.introBar} aria-label="Platform capabilities"><span>Made for the questions<br /><strong>your customers actually ask.</strong></span><div><MessageSquare size={18} />Product guidance</div><div><Layers3 size={18} />Service information</div><div><UsersRound size={18} />Customer enquiries</div></section>

      <section id="experience" className={styles.features} aria-labelledby="experience-title"><div className={styles.sectionHeading}><p className={styles.eyebrow}>HELPFUL BY DESIGN</p><h2 id="experience-title">More than a chat box.<br /><span>A thoughtful customer experience.</span></h2><p>Bring useful answers and clear next steps together, with the controls you need behind the scenes.</p></div><div className={styles.featureGrid}>{features.map((feature, index) => <article key={feature.title} className={styles.feature}><div className={styles.featureIcon}><feature.icon size={23} strokeWidth={1.55} /></div><span className={styles.featureNumber}>0{index + 1}</span><h3>{feature.title}</h3><p>{feature.text}</p></article>)}</div></section>

      <section id="how-it-works" className={styles.how} aria-labelledby="how-title"><div className={styles.howHeading}><p className={styles.eyebrow}>FROM CONTENT TO CONVERSATION</p><h2 id="how-title">Make it yours.<br />Then make it useful.</h2><p>Start with what you already know about your business. Refine the experience before you share it.</p><Link href="/signup" className={styles.lightButton}>Create a workspace<ArrowUpRight size={18} /></Link></div><ol className={styles.steps}><li><span>01</span><div><h3>Bring your knowledge</h3><p>Connect your website or upload documents. Choose the sources your bot should use.</p><div className={styles.stepTags}><span><Globe2 size={12} />Website pages</span><span><FileText size={12} />Documents</span></div></div></li><li><span>02</span><div><h3>Shape the conversation</h3><p>Set its instructions and appearance. Add approved answers, helpful cards and customer actions.</p></div></li><li><span>03</span><div><h3>Test, share, keep improving</h3><p>Try saved questions, review the replies, then embed your widget or share its chat link.</p><div className={styles.stepTags}><span><PanelTop size={12} />Website widget</span><span><ArrowUpRight size={12} />Shareable link</span></div></div></li></ol></section>

      <section className={styles.control} aria-labelledby="control-title"><div className={styles.controlVisual} aria-hidden="true"><div className={styles.controlLine}><span><Globe2 size={20} /></span><i /><span><Layers3 size={20} /></span><i /><span><MessageSquare size={20} /></span></div><div className={styles.controlLabels}><span>Your sources</span><span>Relevant context</span><span>Helpful replies</span></div><div className={styles.controlNote}><ShieldCheck size={18} /><p>Knowledge and settings<br /><strong>organized around each bot.</strong></p></div></div><div><p className={styles.eyebrow}>YOUR WORKSPACE, YOUR CONTROL</p><h2 id="control-title">Give your chatbot context.<br />Give your team clarity.</h2><p>Manage bots, sources, conversations and team access in one workspace. Choose your model, review what visitors ask and update your knowledge as your business changes.</p><a href="#questions" className={styles.textLink}>A few things to know<ArrowRight size={17} /></a></div></section>

      <section id="questions" className={styles.faq} aria-labelledby="faq-title"><div><p className={styles.eyebrow}>A GOOD PLACE TO START</p><h2 id="faq-title">A few questions.<br />Clear answers.</h2><p>What to know before you create your first chatbot.</p></div><div className={styles.faqList}>{questions.map((item) => <details key={item.question}><summary>{item.question}<ChevronDown size={18} /></summary><p>{item.answer}</p></details>)}</div></section>

      <section className={styles.finalCta} aria-labelledby="start-title"><span className={styles.ctaIcon}><BrandMark size={36} /></span><p className={styles.eyebrow}>LET’S MAKE YOUR KNOWLEDGE USEFUL</p><h2 id="start-title">Your next good conversation<br />starts here.</h2><Link href="/signup" className={styles.primaryButton}>Build your chatbot<ArrowUpRight size={19} /></Link></section>
    </main>

    <footer className={styles.footer}><Link href="/" className={styles.brand}><span className={styles.brandMark}><BrandMark size={28} /></span>Chatbot SaaS</Link><p>Thoughtful conversations, built around your business.</p><nav aria-label="Footer navigation"><a href="#experience">Experience</a><a href="#questions">Questions</a><Link href="/login">Sign in</Link></nav><small>© 2026 Chatbot SaaS</small></footer>
  </div>;
}
