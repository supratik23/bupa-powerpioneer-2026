import { useRef, useState } from 'react'
import type { SubmitEvent, KeyboardEvent } from 'react'
import './App.css'

const API_URL = 'http://localhost:8000/agent/invoke'
const sessionId = crypto.randomUUID()

type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  tokenUsage?: string | null
  imageUrl?: string
}

type AgentResponse = {
  response: string
  token_usage?: string | null
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [query, setQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [image, setImage] = useState<File | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)

  async function sendMessage(event?: SubmitEvent<HTMLFormElement>) {
    event?.preventDefault()
    const trimmedQuery = query.trim()
    if ((!trimmedQuery && !image) || isLoading) return

    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', content: trimmedQuery || 'Analyze this image.', imageUrl: imagePreview || undefined },
    ])
    setQuery('')
    const attachedImage = image
    setImage(null)
    setImagePreview(null)
    setError(null)
    setIsLoading(true)

    try {
      const formData = new FormData()
      formData.append('query', trimmedQuery)
      formData.append('session_id', sessionId)
      formData.append('user_id', 'web-user')
      formData.append('organization_id', 'web-organization')
      formData.append('organization_name', 'Med Agent Workspace')
      if (attachedImage) formData.append('image', attachedImage)

      const response = await fetch(API_URL, {
        method: 'POST',
        body: formData,
      })

      const data = (await response.json()) as AgentResponse
      if (!response.ok) {
        throw new Error(data.response || `Request failed with status ${response.status}`)
      }

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: data.response,
          tokenUsage: data.token_usage,
        },
      ])
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to reach the agent. Check that the backend is running.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  function handleImageChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selectedFile = event.target.files?.[0]
    if (!selectedFile) return
    setImage(selectedFile)
    setImagePreview(URL.createObjectURL(selectedFile))
    event.target.value = ''
  }

  function removeImage() {
    if (imagePreview) URL.revokeObjectURL(imagePreview)
    setImage(null)
    setImagePreview(null)
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">+</div>
          <div>
            <p className="eyebrow">Clinical intelligence</p>
            <h1>Med Agent</h1>
          </div>
        </div>
      </header>

      <section className="chat-panel" aria-label="Medical agent chat">
        <div className="chat-heading">
          <div>
            <h2>How can I help today?</h2>
            <p className="heading-copy">Ask about clinical information, care tasks, or your connected tools.</p>
          </div>
        </div>

        <div className="message-list" aria-live="polite">
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="pulse-icon" aria-hidden="true">✦</div>
              <p>Start a conversation with your agent.</p>
              <span>Responses will appear here as they are generated.</span>
            </div>
          )}
          {messages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              <div className="avatar" aria-hidden="true">{message.role === 'user' ? 'You' : 'MA'}</div>
              <div className="message-content">
                <div className="message-meta">{message.role === 'user' ? 'You' : 'Med Agent'}</div>
                {message.imageUrl && <img className="message-image" src={message.imageUrl} alt="Attached for analysis" />}
                {message.content && <p>{message.content}</p>}
                {message.tokenUsage && <small>{message.tokenUsage}</small>}
              </div>
            </article>
          ))}
          {isLoading && (
            <article className="message-row assistant">
              <div className="avatar" aria-hidden="true">MA</div>
              <div className="message-content"><div className="message-meta">Med Agent</div><div className="typing"><i /><i /><i /></div></div>
            </article>
          )}
        </div>

        {error && <p className="error-message" role="alert">{error}</p>}
        <form className="composer" onSubmit={sendMessage}>
          <input ref={fileInputRef} className="visually-hidden" type="file" accept="image/*" onChange={handleImageChange} />
          <input ref={cameraInputRef} className="visually-hidden" type="file" accept="image/*" capture="environment" onChange={handleImageChange} />
          {imagePreview && (
            <div className="attachment-preview">
              <img src={imagePreview} alt="Selected attachment" />
              <button type="button" className="remove-attachment" onClick={removeImage} aria-label="Remove image">×</button>
            </div>
          )}
          <div className="composer-tools">
            <button type="button" className="icon-button" onClick={() => fileInputRef.current?.click()} aria-label="Upload an image" title="Upload an image">＋</button>
            <button type="button" className="icon-button" onClick={() => cameraInputRef.current?.click()} aria-label="Take a photo" title="Take a photo">◎</button>
          </div>
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="Ask your medical agent..."
            aria-label="Message your medical agent"
            rows={1}
            disabled={isLoading}
          />
          <button type="submit" aria-label="Send message" disabled={(!query.trim() && !image) || isLoading}>Send <span aria-hidden="true">↗</span></button>
        </form>
        <p className="composer-hint">Press Enter to send · Shift + Enter for a new line</p>
      </section>
    </main>
  )
}

export default App
