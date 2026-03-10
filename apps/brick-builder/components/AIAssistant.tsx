'use client';

import { useState, useRef, useEffect } from 'react';
import { useBrickStore, type Brick } from '@/lib/store';
import axios from 'axios';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export function AIAssistant() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content:
        'Hi! I can help you build with LEGO bricks. Try saying "Build me a house" or "Create a tower".',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const bricks = useBrickStore((state) => state.bricks);
  const addBrick = useBrickStore((state) => state.addBrick);
  const selectedColor = useBrickStore((state) => state.selectedColor);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // For now, generate simple patterns based on keywords
      const response = await generateBrickPattern(input);

      // Parse the response and add bricks
      if (response.bricks && Array.isArray(response.bricks)) {
        response.bricks.forEach((brickData: any) => {
          const newBrick: Brick = {
            id: `brick-${Date.now()}-${Math.random()}`,
            type: brickData.type || 'brick-2x2',
            position: brickData.position || [0, 0, 0],
            rotation: [0, 0, 0],
            color: brickData.color || selectedColor,
          };
          addBrick(newBrick);
        });
      }

      const assistantMessage: Message = {
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content: response.message || 'I have added bricks to your build!',
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Error:', error);
      const errorMessage: Message = {
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content:
          'Sorry, I encountered an error. Try a simpler request like "add bricks".',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white border-l border-gray-300">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-blue-700 text-white p-4 border-b border-blue-700">
        <h2 className="font-bold text-lg">AI Assistant</h2>
        <p className="text-sm text-blue-100">Build with AI suggestions</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-xs px-4 py-2 rounded-lg ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-br-none'
                  : 'bg-gray-200 text-gray-900 rounded-bl-none'
              }`}
            >
              <p className="text-sm">{msg.content}</p>
              <p
                className={`text-xs mt-1 ${
                  msg.role === 'user'
                    ? 'text-blue-100'
                    : 'text-gray-500'
                }`}
              >
                {msg.timestamp.toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </p>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-200 text-gray-900 px-4 py-2 rounded-lg rounded-bl-none">
              <div className="flex gap-1">
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-100"></div>
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-200"></div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-300 p-4 bg-gray-50">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Build me a house..."
            disabled={isLoading}
            className="flex-1 px-3 py-2 rounded border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded font-medium hover:bg-blue-700 disabled:bg-gray-400 transition"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

async function generateBrickPattern(
  prompt: string
): Promise<{ message: string; bricks: any[] }> {
  // Simple pattern generation without external API
  const lowerPrompt = prompt.toLowerCase();

  if (
    lowerPrompt.includes('house') ||
    lowerPrompt.includes('home') ||
    lowerPrompt.includes('building')
  ) {
    return {
      message: 'Building a house foundation...',
      bricks: [
        { type: 'brick-2x4', position: [0, 0, 0], color: '#DC143C' },
        { type: 'brick-2x4', position: [3.2, 0, 0], color: '#DC143C' },
        { type: 'brick-2x4', position: [0, 1.2, 0], color: '#DC143C' },
        { type: 'brick-2x4', position: [3.2, 1.2, 0], color: '#DC143C' },
      ],
    };
  }

  if (lowerPrompt.includes('tower') || lowerPrompt.includes('tall')) {
    return {
      message: 'Building a tower...',
      bricks: [
        { type: 'brick-2x2', position: [0, 0, 0], color: '#0055BF' },
        { type: 'brick-2x2', position: [0, 1.2, 0], color: '#0055BF' },
        { type: 'brick-2x2', position: [0, 2.4, 0], color: '#0055BF' },
        { type: 'brick-2x2', position: [0, 3.6, 0], color: '#0055BF' },
        { type: 'brick-1x1', position: [0.8, 4.8, 0], color: '#F7BE16' },
      ],
    };
  }

  if (lowerPrompt.includes('wall') || lowerPrompt.includes('fence')) {
    return {
      message: 'Building a wall...',
      bricks: [
        { type: 'brick-2x4', position: [0, 0, 0], color: '#05131D' },
        { type: 'brick-2x4', position: [3.2, 0, 0], color: '#05131D' },
        { type: 'brick-2x4', position: [6.4, 0, 0], color: '#05131D' },
      ],
    };
  }

  if (lowerPrompt.includes('add') || lowerPrompt.includes('place')) {
    return {
      message: 'Adding a brick...',
      bricks: [{ type: 'brick-2x2', position: [0, 0, 0], color: '#239B24' }],
    };
  }

  return {
    message:
      'Try "build a house", "tower", "wall", or "add bricks" to get started!',
    bricks: [],
  };
}
