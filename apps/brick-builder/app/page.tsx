import Link from 'next/link';

export const metadata = {
  title: 'Brick Builder - AI-Assisted LEGO Design',
  description: 'Build LEGO creations with AI suggestions',
};

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white overflow-hidden">
      {/* Navigation */}
      <nav className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <span className="text-3xl">🧱</span>
          <span className="text-xl font-bold">Brick Builder</span>
        </div>
        <div className="flex gap-4">
          <a
            href="#features"
            className="text-slate-300 hover:text-white transition"
          >
            Features
          </a>
          <a
            href="#about"
            className="text-slate-300 hover:text-white transition"
          >
            About
          </a>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative px-6 py-20 max-w-6xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
          {/* Left: Content */}
          <div className="space-y-6">
            <h1 className="text-5xl md:text-6xl font-bold leading-tight">
              Build Your
              <br />
              <span className="bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">
                LEGO Creations
              </span>
            </h1>

            <p className="text-xl text-slate-300 leading-relaxed">
              An AI-powered 3D builder for LEGO designs. Get intelligent
              suggestions, visualize in real-time, and export your builds.
            </p>

            <div className="flex flex-col sm:flex-row gap-4 pt-4">
              <Link
                href="/builder"
                className="px-8 py-3 bg-gradient-to-r from-blue-600 to-blue-500 rounded-lg font-bold text-lg hover:shadow-lg hover:shadow-blue-500/50 transition transform hover:scale-105 text-center"
              >
                Start Building
              </Link>
              <button className="px-8 py-3 border-2 border-slate-400 rounded-lg font-bold text-lg hover:bg-slate-800 transition">
                Learn More
              </button>
            </div>
          </div>

          {/* Right: 3D Preview */}
          <div className="relative h-96 md:h-full min-h-96 rounded-xl overflow-hidden bg-gradient-to-br from-slate-800 to-slate-900 border border-slate-700/50 shadow-2xl">
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-4">
                <div className="text-6xl animate-bounce">🧱</div>
                <p className="text-slate-400">3D Preview Coming Soon</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="px-6 py-20 bg-slate-800/50 border-t border-slate-700/50">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-4xl font-bold text-center mb-16">Features</h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Feature 1 */}
            <div className="bg-slate-800/80 border border-slate-700 rounded-lg p-6 hover:border-blue-500 transition">
              <div className="text-4xl mb-4">🤖</div>
              <h3 className="text-xl font-bold mb-3">AI Suggestions</h3>
              <p className="text-slate-300">
                Just describe what you want to build and our AI will suggest
                brick placements.
              </p>
            </div>

            {/* Feature 2 */}
            <div className="bg-slate-800/80 border border-slate-700 rounded-lg p-6 hover:border-blue-500 transition">
              <div className="text-4xl mb-4">🎨</div>
              <h3 className="text-xl font-bold mb-3">Real-time 3D View</h3>
              <p className="text-slate-300">
                See your creation come to life in 3D with interactive camera
                controls.
              </p>
            </div>

            {/* Feature 3 */}
            <div className="bg-slate-800/80 border border-slate-700 rounded-lg p-6 hover:border-blue-500 transition">
              <div className="text-4xl mb-4">💾</div>
              <h3 className="text-xl font-bold mb-3">Save & Export</h3>
              <p className="text-slate-300">
                Save your builds locally or export them for sharing and further
                editing.
              </p>
            </div>

            {/* Feature 4 */}
            <div className="bg-slate-800/80 border border-slate-700 rounded-lg p-6 hover:border-blue-500 transition">
              <div className="text-4xl mb-4">🎯</div>
              <h3 className="text-xl font-bold mb-3">Grid Snapping</h3>
              <p className="text-slate-300">
                Bricks automatically snap to grid for perfectly aligned
                structures.
              </p>
            </div>

            {/* Feature 5 */}
            <div className="bg-slate-800/80 border border-slate-700 rounded-lg p-6 hover:border-blue-500 transition">
              <div className="text-4xl mb-4">↩️</div>
              <h3 className="text-xl font-bold mb-3">Undo/Redo</h3>
              <p className="text-slate-300">
                Never lose progress with unlimited undo and redo functionality.
              </p>
            </div>

            {/* Feature 6 */}
            <div className="bg-slate-800/80 border border-slate-700 rounded-lg p-6 hover:border-blue-500 transition">
              <div className="text-4xl mb-4">🎨</div>
              <h3 className="text-xl font-bold mb-3">LEGO Colors</h3>
              <p className="text-slate-300">
                Choose from authentic LEGO colors or pick any custom color you
                want.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* About Section */}
      <section id="about" className="px-6 py-20">
        <div className="max-w-4xl mx-auto text-center space-y-6">
          <h2 className="text-4xl font-bold">About Brick Builder</h2>
          <p className="text-lg text-slate-300 leading-relaxed">
            Brick Builder is a showcase project from OpenClaw, demonstrating the
            power of AI-assisted creative tools. Built with React, Three.js, and
            TypeScript, it combines 3D visualization with intelligent AI
            suggestions to make LEGO building more intuitive and fun.
          </p>
          <div className="flex justify-center gap-4 pt-4">
            <a
              href="https://github.com"
              className="px-6 py-2 border border-slate-400 rounded hover:bg-slate-800 transition"
            >
              GitHub
            </a>
            <a
              href="https://openclaw.io"
              className="px-6 py-2 bg-blue-600 rounded hover:bg-blue-700 transition"
            >
              OpenClaw
            </a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-700/50 px-6 py-6 text-center text-slate-400">
        <p>
          &copy; 2026 Brick Builder. Part of the OpenClaw project ecosystem.
        </p>
      </footer>
    </div>
  );
}
