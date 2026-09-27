import { useEffect, useRef, useState } from 'react'
import { ArrowRight, AudioLines, ChevronDown, Headphones, Menu, PackageCheck, Search, Send, ShoppingBag, Sparkles, Truck, UserRound, X } from 'lucide-react'

const API = import.meta.env.VITE_API_BASE_URL || ''
const products = [
  { name: 'Studio Pro Headphones', category: 'Audio', price: '₹8,999', old: '₹12,999', rating: '4.8', image: 'photo-1505740420928-5e560c06d30e', tag: 'BESTSELLER' },
  { name: 'Everyday Smartwatch', category: 'Wearables', price: '₹5,499', old: '₹7,999', rating: '4.6', image: 'photo-1523275335684-37898b6baf30', tag: 'JUST IN' },
  { name: 'Pocket Camera', category: 'Cameras', price: '₹24,990', old: '₹29,990', rating: '4.9', image: 'photo-1516035069371-29a1b244cc32', tag: '−17%' },
  { name: 'Soundbar Mini', category: 'Home audio', price: '₹6,490', old: '₹8,490', rating: '4.7', image: 'photo-1545454675-3531b543be5d', tag: 'TOP RATED' },
]
const imageUrl = (id, width = 700) => `https://images.unsplash.com/${id}?auto=format&fit=crop&w=${width}&q=85`

function Storefront() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([{ role: 'assistant', content: 'Hi there! 👋 I’m Gigi, your GSR shopping assistant. I can help track an order, start a return, or answer a question. What can I do for you?' }])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [session, setSession] = useState(() => localStorage.getItem('gsr-session') || crypto.randomUUID())
  const [customer, setCustomer] = useState('')
  const [accountOpen, setAccountOpen] = useState(false)
  const [authMode, setAuthMode] = useState('login')
  const [authName, setAuthName] = useState('')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [basket, setBasket] = useState(0)
  const [notice, setNotice] = useState('')
  const bottomRef = useRef(null)
  useEffect(() => { localStorage.setItem('gsr-session', session) }, [session])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, open])
  useEffect(() => {
    fetch(`${API}/auth/me`, { credentials: 'include' }).then(r => r.ok ? r.json() : null)
      .then(account => { if (account) setCustomer(account.customer_id) }).catch(() => {})
  }, [])

  async function sendMessage(value = text) {
    const message = value.trim()
    if (!message || busy) return
    setMessages(prev => [...prev, { role: 'user', content: message }]); setText(''); setBusy(true)
    try {
      const response = await fetch(`${API}/chat`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: session, message }) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Something went wrong. Please try again.')
      setMessages(prev => [...prev, { role: 'assistant', content: data.response, intent: data.intent, escalated: data.escalated, ticket: data.ticket_id, timings: data.timings_ms }])
    } catch (error) {
      setMessages(prev => [...prev, { role: 'assistant', content: `I couldn't reach support right now. ${error.message} Please try again in a moment.` }])
    } finally { setBusy(false) }
  }

  async function submitAuth(e) {
    e.preventDefault(); setBusy(true)
    try {
      const signup = authMode === 'signup'
      const response = await fetch(`${API}/auth/${signup ? 'signup' : 'login'}`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(signup ? { name: authName, email: authEmail, password: authPassword } : { email: authEmail, password: authPassword }),
      })
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Could not sign in')
      setCustomer(data.customer_id); setSession(crypto.randomUUID())
      setMessages([{ role: 'assistant', content: `Hi ${data.name}! I’m Gigi, and I’m here if you need help with an order or anything else.` }])
      setAuthPassword(''); setAccountOpen(false); setNotice(signup ? 'Your GSR account is ready.' : `Welcome back, ${data.name}.`)
    } catch (err) { setNotice(err.message) } finally { setBusy(false) }
  }

  async function signOut() {
    await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'include' }).catch(() => {})
    setCustomer(''); setSession(crypto.randomUUID()); setMessages([{ role: 'assistant', content: 'Hi there! 👋 I’m Gigi, your GSR shopping assistant. I can help track an order, start a return, or answer a question. What can I do for you?' }]); setAccountOpen(false)
  }

  return <>
    <div className="announcement">A little extra joy: free delivery on your first order <span>✦</span></div>
    <header className="header">
      <button className="icon-button mobile-menu" aria-label="Open menu"><Menu size={21}/></button>
      <a className="brand" href="#top"><span className="brand-mark">g</span><span>gsr<span className="brand-dot">.</span></span></a>
      <nav className="nav"><a href="#shop">Shop</a><a href="#shop">Electronics</a><a href="#shop">Home & living</a><a href="#shop">New arrivals</a></nav>
      <div className="header-actions"><button className="search-trigger"><Search size={17}/><span>Search products</span><kbd>⌘ K</kbd></button><button className="icon-button account-button" aria-label="Account" onClick={() => setAccountOpen(v => !v)}><UserRound size={19}/></button><button className="bag-button" aria-label="Shopping bag"><ShoppingBag size={19}/><span className="bag-count">{basket}</span></button></div>
    </header>
    {accountOpen && <div className="account-popover"><button className="popover-close" onClick={() => setAccountOpen(false)}><X size={16}/></button><h3>{customer ? 'Your GSR account' : (authMode === 'login' ? 'Welcome back' : 'Create your account')}</h3>{customer ? <><p className="muted">Your account is signed in and ready for personalized support.</p><button className="text-button" onClick={signOut}>Sign out</button></> : <><p className="muted">{authMode === 'login' ? 'Sign in with your email and password.' : 'Create an account to get personalized order support.'}</p><form onSubmit={submitAuth}>{authMode === 'signup' && <input autoComplete="name" required value={authName} onChange={e => setAuthName(e.target.value)} placeholder="Full name"/>}<input type="email" autoComplete="email" required value={authEmail} onChange={e => setAuthEmail(e.target.value)} placeholder="Email address"/><input type="password" autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} minLength={12} required value={authPassword} onChange={e => setAuthPassword(e.target.value)} placeholder={authMode === 'login' ? 'Password' : 'Password (12+ characters)'}/><button className="small-primary" disabled={busy}>{busy ? 'Please wait…' : authMode === 'login' ? 'Sign in' : 'Create account'}</button></form><button className="text-button auth-switch" onClick={() => setAuthMode(authMode === 'login' ? 'signup' : 'login')}>{authMode === 'login' ? 'New to GSR? Create an account' : 'Already have an account? Sign in'}</button></>}</div>}
    <main id="top">
      <section className="hero"><div className="hero-copy"><div className="eyebrow"><span/> THE EVERYDAY EDITION</div><h1>Good things.<br/><em>Great finds.</em></h1><p>Thoughtful tech and everyday essentials, picked to make your life a little brighter.</p><a className="hero-cta" href="#shop">Explore the collection <ArrowRight size={17}/></a><div className="hero-trust"><span><Truck size={16}/> Free delivery over ₹999</span><span><PackageCheck size={16}/> Easy 7-day returns</span></div></div><div className="hero-image"><img src={imageUrl('photo-1498049794561-7780e7231661', 1200)} alt="A curated collection of modern electronics"/><div className="hero-sticker"><span>CURATED<br/>FOR YOU</span><Sparkles size={17}/></div><div className="image-caption">Little upgrades, big everyday energy.</div></div><div className="hero-index"><span>01</span> / 04</div></section>
      <section className="benefits"><div><span className="benefit-icon">✳</span><span><b>Picked with purpose</b><small>Better choices, made easy</small></span></div><div><span className="benefit-icon">↗</span><span><b>Fast, happy delivery</b><small>Right to your doorstep</small></span></div><div><span className="benefit-icon">♡</span><span><b>Here when you need us</b><small>Real help, no runaround</small></span></div></section>
      <section id="shop" className="collection"><div className="section-heading"><div><div className="eyebrow">A FEW CURRENT FAVOURITES</div><h2>Good finds, <em>right now.</em></h2></div><a href="#shop" className="view-all">View all products <ArrowRight size={16}/></a></div><div className="product-grid">{products.map((p, i) => <article className="product-card" key={p.name}><div className="product-image"><img src={imageUrl(p.image)} alt={p.name}/><span className="product-tag">{p.tag}</span><button className="quick-add" onClick={() => {setBasket(n => n + 1); setNotice(`${p.name} added to your bag.`)}}>＋ <span>Quick add</span></button></div><div className="product-meta"><span>{p.category}</span><span className="rating">★ {p.rating}</span></div><h3>{p.name}</h3><div className="price">{p.price} <del>{p.old}</del></div></article>)}</div></section>
      <section className="help-banner"><div className="help-icon"><Headphones size={24}/></div><div><h2>Need a hand with something?</h2><p>Order updates, returns, product questions — Gigi’s right here.</p></div><button onClick={() => setOpen(true)}>Chat with Gigi <ArrowRight size={16}/></button></section>
    </main>
    <footer><a className="brand footer-brand" href="#top"><span className="brand-mark">g</span><span>gsr<span className="brand-dot">.</span></span></a><span>Made for the everyday. © 2026 GSR Retail.</span><span className="footer-links">Help & support <span>·</span> Shipping & returns</span></footer>
    {notice && <button className="toast" onClick={() => setNotice('')}>{notice}<X size={14}/></button>}
    {!open && <button className="chat-launcher" onClick={() => setOpen(true)} aria-label="Chat with Gigi"><span className="launcher-spark"><Sparkles size={16}/></span><span className="launcher-label">Need a hand?</span><span className="chat-face">g</span><span className="online-dot"/></button>}
    {open && <section className="chat-panel" aria-label="GSR customer support chat"><header className="chat-header"><div className="bot-avatar"><span>g</span><i/></div><div className="chat-head-copy"><b>Gigi <span className="verified">✳</span></b><small><span className="status-dot"/> Here to help, anytime</small></div><button className="chat-close" onClick={() => setOpen(false)} aria-label="Close chat"><X size={19}/></button></header><div className="chat-context"><Sparkles size={14}/> Your GSR shopping assistant</div><div className="chat-messages">{messages.map((m, i) => <div className={`message-row ${m.role}`} key={i}>{m.role === 'assistant' && <span className="message-avatar">g</span>}<div className="message-wrap"><div className="bubble">{m.content}</div>{m.intent && <small className={`message-status ${m.escalated ? 'escalated' : ''}`}>{m.escalated ? 'Support ticket created' : 'Resolved'} · {m.intent}{m.timings?.request_total != null ? ` · ${(m.timings.request_total / 1000).toFixed(1)}s` : ''}{m.ticket ? ` · ${m.ticket}` : ''}</small>}</div></div>)}{busy && <div className="message-row assistant"><span className="message-avatar">g</span><div className="bubble typing"><i/><i/><i/></div></div>}<div ref={bottomRef}/></div><div className="suggestions"><button onClick={() => sendMessage('Where is my order ord_000519?')}>Track my order</button><button onClick={() => sendMessage('What is your return policy?')}>Returns & refunds</button></div><form className="chat-compose" onSubmit={e => {e.preventDefault(); sendMessage()}}><input value={text} onChange={e => setText(e.target.value)} placeholder="Ask Gigi anything…" disabled={busy}/><button type="submit" disabled={!text.trim() || busy} aria-label="Send message"><Send size={17}/></button></form><div className="chat-footnote"><AudioLines size={12}/> Gigi is an AI assistant. Replies may occasionally be inaccurate.</div></section>}
  </>
}

export default Storefront
