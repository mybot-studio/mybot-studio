import React, { useState, useEffect, useCallback, useRef, useSyncExternalStore } from 'react';
import { createGraphHistory, persistGraphSnapshot, graphHistoryShortcut, isSaveShortcut, isTextEditing, cursorToFlowPosition } from './graphHistory.js';
import { migrateEmbeddedKeyboards } from './components/Nodes/keyboardGraph.mjs';
import {
  applyNodeChanges,
  applyEdgeChanges,
  addEdge
} from '@xyflow/react';

import LoginPage from './components/Auth/LoginPage';
import Sidebar from './components/Sidebar/Sidebar';
import SettingsView from './components/Settings/SettingsView';
import PluginsView from './components/Plugins/PluginsView';
import BotsList from './components/Dashboard/BotsList';
import Navbar from './components/Header/Navbar';
import BotSettingsModal from './components/Header/BotSettingsModal';
import Canvas from './components/Canvas/Canvas';
import QuickSearchPalette from './components/QuickSearch/QuickSearchPalette';
import TelegramMockup from './components/Mockup/TelegramMockup';
import PluginsModal from './components/Plugins/PluginsModal';

import { useI18n } from './locales/i18n';
import { api } from './services/api';

export default function App() {
  const { t } = useI18n();
  const [theme, setTheme] = useState(() => localStorage.getItem('mybot_theme') || 'dark');
  
  // Auth state
  const [isAuthenticated, setIsAuthenticated] = useState(() => !!localStorage.getItem('mybot_token'));

  // Navigation state (persisted across refreshes)
  const [view, setView] = useState(() => localStorage.getItem('mybot_view') || 'dashboard');
  const [sidebarTab, setSidebarTab] = useState('profiles'); // 'profiles', 'plugins', 'settings'

  // Bot & Flow State (persisted across refreshes)
  const [bots, setBots] = useState([]);
  const [currentBot, setCurrentBot] = useState(() => {
    try {
      const raw = localStorage.getItem('mybot_current_bot');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });
  const [loadingBots, setLoadingBots] = useState(true);

  const [history] = useState(() => createGraphHistory());
  const { nodes, edges } = useSyncExternalStore(history.subscribe, history.getSnapshot);
  const isDirty = useSyncExternalStore(history.subscribe, history.isDirty);
  const setNodes = useCallback(updater => history.update(graph => ({ ...graph,
    nodes: typeof updater === 'function' ? updater(graph.nodes) : updater,
  })), [history]);
  const setEdges = useCallback(updater => history.update(graph => ({ ...graph,
    edges: typeof updater === 'function' ? updater(graph.edges) : updater,
  })), [history]);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const selectedNode = nodes.find(node => node.id === selectedNodeId) || null;
  const [isSaving, setIsSaving] = useState(false);
  const [flowReady, setFlowReady] = useState(false);
  const flowSession = useRef(0);
  const loadedBotId = useRef(null);
  const savingRequest = useRef(null);
  const flowInstance = useRef(null);
  const beginDrag = useCallback(() => history.begin(), [history]);
  const endDrag = useCallback(() => history.end(), [history]);
  const clearFlow = useCallback(() => {
    flowSession.current += 1;
    loadedBotId.current = null;
    savingRequest.current = null;
    setIsSaving(false);
    setFlowReady(false);
    setSelectedNodeId(null);
    history.reset();
  }, [history]);

  // Modals & Overlays
  const [quickSearchOpen, setQuickSearchOpen] = useState(false);
  const [quickSearchPos, setQuickSearchPos] = useState({ x: 200, y: 200 });
  const [pluginsModalOpen, setPluginsModalOpen] = useState(false);
  const [botSettingsOpen, setBotSettingsOpen] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [pendingNodePos, setPendingNodePos] = useState(null);

  // Theme application
  useEffect(() => {
    localStorage.setItem('mybot_theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
    } else {
      document.documentElement.classList.remove('dark');
      document.documentElement.classList.add('light');
    }
  }, [theme]);

  // Load Bot Flow
  const loadBotFlow = useCallback(async (botId) => {
    clearFlow();
    const session = flowSession.current;
    try {
      const flow = await api.getFlow(botId);
      if (session !== flowSession.current) return;
      if (flow) {
        const migrated = migrateEmbeddedKeyboards(flow);
        history.reset({ nodes: migrated.nodes, edges: migrated.edges });
        history.markSaved({ nodes: flow.nodes || [], edges: flow.edges || [] });
        loadedBotId.current = String(botId);
        setFlowReady(true);
      }
    } catch (e) {
      // Never permit a failed load to overwrite the remote flow with an empty graph.
      console.error(e);
    }
  }, [clearFlow, history]);

  // Load Bots on mount or auth change
  const loadBots = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      setLoadingBots(true);
      const list = await api.getBots();
      setBots(list);

      // Verify and sync currentBot from freshly loaded list
      const savedBotId = localStorage.getItem('mybot_current_bot_id');
      const savedView = localStorage.getItem('mybot_view');
      if (savedView === 'studio' && savedBotId) {
        const found = list.find((b) => String(b.id) === String(savedBotId));
        if (found) {
          setCurrentBot(found);
          localStorage.setItem('mybot_current_bot', JSON.stringify(found));
        } else {
          clearFlow();
          // If stored bot ID was deleted, gracefully return to dashboard
          setView('dashboard');
          setCurrentBot(null);
          localStorage.setItem('mybot_view', 'dashboard');
          localStorage.removeItem('mybot_current_bot');
          localStorage.removeItem('mybot_current_bot_id');
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingBots(false);
    }
  }, [isAuthenticated, clearFlow]);

  useEffect(() => {
    if (isAuthenticated) {
      loadBots();
      api.checkUpdate().then(setUpdateInfo).catch(() => {});
      
      // If we were in studio view before refresh, immediately load flow for saved bot
      const savedBotId = localStorage.getItem('mybot_current_bot_id');
      const savedView = localStorage.getItem('mybot_view');
      if (savedView === 'studio' && savedBotId) {
        loadBotFlow(savedBotId);
      }
    }
  }, [isAuthenticated, loadBots, loadBotFlow]);

  const handleSelectBot = (bot) => {
    setCurrentBot(bot);
    localStorage.setItem('mybot_current_bot', JSON.stringify(bot));
    localStorage.setItem('mybot_current_bot_id', String(bot.id));
    localStorage.setItem('mybot_view', 'studio');
    loadBotFlow(bot.id);
    setView('studio');
  };

  const handleBackToDashboard = () => {
    clearFlow();
    setView('dashboard');
    setCurrentBot(null);
    localStorage.setItem('mybot_view', 'dashboard');
    localStorage.removeItem('mybot_current_bot');
    localStorage.removeItem('mybot_current_bot_id');
    loadBots();
  };

  const handleLogout = () => {
    clearFlow();
    localStorage.removeItem('mybot_token');
    localStorage.removeItem('mybot_view');
    localStorage.removeItem('mybot_current_bot');
    localStorage.removeItem('mybot_current_bot_id');
    setIsAuthenticated(false);
  };

  // api.js drops the stored token and fires this event whenever the backend
  // rejects our JWT (expiry, or an engine restart with a new secret), so the
  // panel returns to the login screen instead of sitting on a page where every
  // request silently 401s. The ref keeps the listener stable.
  const logoutRef = useRef(handleLogout);
  logoutRef.current = handleLogout;

  useEffect(() => {
    const onUnauthorized = () => logoutRef.current();
    window.addEventListener('mybot:unauthorized', onUnauthorized);
    return () => window.removeEventListener('mybot:unauthorized', onUnauthorized);
  }, []);

  const handleUpdateBot = (updatedBot) => {
    setCurrentBot(updatedBot);
    localStorage.setItem('mybot_current_bot', JSON.stringify(updatedBot));
    setBots((prev) => prev.map((b) => (b.id === updatedBot.id ? updatedBot : b)));
  };

  const handleToggleRunBot = async () => {
    if (!currentBot) return;
    try {
      const res = await api.toggleBotActive(currentBot.id);
      const updated = { ...currentBot, is_active: res.is_active };
      handleUpdateBot(updated);
    } catch (e) {
      console.error('Error toggling bot run status:', e);
    }
  };

  // Node & Edge Handlers
  const handleNodesChange = useCallback(changes => {
    history.update(graph => ({ ...graph, nodes: applyNodeChanges(changes, graph.nodes) }));
  }, [history]);
  const handleEdgesChange = useCallback(changes => {
    history.update(graph => ({ ...graph, edges: applyEdgeChanges(changes, graph.edges) }));
  }, [history]);

  const handleConnect = useCallback(
    (params) => {
      setEdges((eds) => addEdge({ ...params, animated: true }, eds));

    },
    [setEdges]
  );

  const handleNodeClick = useCallback((_, node) => {
    setSelectedNodeId(node.id);
  }, []);

  const handleUpdateNodeData = (nodeId, newData) => {
    setNodes((nds) =>
      nds.map((node) => {
        if (node.id === nodeId) {
          return { ...node, data: newData };
        }
        return node;
      })
    );


  };

  // Save Flow
  const handleSaveFlow = useCallback(async () => {
    if (!currentBot || !flowReady || view !== 'studio' || savingRequest.current ||
        loadedBotId.current !== String(currentBot.id)) return;
    const session = flowSession.current;
    const request = {};
    savingRequest.current = request;
    setIsSaving(true);
    const isCurrent = () => session === flowSession.current;
    try {
      const result = await persistGraphSnapshot({ history, botId: currentBot.id, isCurrent,
        saveFlow: (id, data) => api.saveFlow(id, data),
        syncCommands: id => api.syncCommands(id),
      });
      if (isCurrent() && result.status === 'save-error') window.alert(t('common.flow_save_error'));
      if (isCurrent() && result.status === 'sync-error') window.alert(t('common.flow_commands_sync_error'));
    } finally {
      if (savingRequest.current === request) {
        savingRequest.current = null;
        setIsSaving(false);
      }
    }
  }, [currentBot, flowReady, view, history, t]);

  // Export / Import
  const handleExportFlow = async () => {
    if (!currentBot) return;
    try {
      const data = await api.exportFlow(currentBot.id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mybot-${currentBot.username}-flow.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
    }
  };

  const handleImportFlow = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !currentBot) return;
    try {
      await api.importFlow(currentBot.id, file);
      loadBotFlow(currentBot.id);
    } catch (err) {
      alert(t('common.template_error', { error: err.message }));
    }
  };

  // Quick Search Add Node
  const handleAddNode = (def, pos) => {
    const position = pendingNodePos || pos || (flowInstance.current
      ? cursorToFlowPosition(flowInstance.current.screenToFlowPosition, quickSearchPos) : { x: 0, y: 0 });
    const newNode = {
      id: `node_${Date.now()}`,
      type: def.type,
      position,
      data: { ...def.data }
    };
    setNodes((nds) => [...nds, newNode]);
    setSelectedNodeId(newNode.id);
    setPendingNodePos(null);

  };

  // Add node at specific flow position (right-click)
  const handleAddNodeAt = (clientX, clientY, flowPos) => {
    setQuickSearchPos({ x: clientX, y: clientY });
    setPendingNodePos(flowPos || null);
    setQuickSearchOpen(true);
  };

  // Delete node and its connected edges
  const handleDeleteNode = (nodeId) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId));
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
    if (selectedNodeId === nodeId) setSelectedNodeId(null);

  };

  // Delete a single edge
  const handleDeleteEdge = (edgeId) => {
    setEdges((eds) => eds.filter((e) => e.id !== edgeId));

  };

  // Prevent closing / reloading if there are unsaved flow changes
  useEffect(() => {
    const handleBeforeUnload = (e) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = '';
        return e.returnValue;
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isDirty]);

  // Capture before graph fields stop propagation; unrelated forms retain native undo.
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (view !== 'studio') return;
      if (isSaveShortcut(e)) {
        e.preventDefault();
        handleSaveFlow();
        return;
      }
      if (botSettingsOpen || pluginsModalOpen || quickSearchOpen) return;
      const action = graphHistoryShortcut(e);
      if (action) {
        e.preventDefault();
        e.stopPropagation();
        history[action]();
        return;
      }
      if ((e.ctrlKey && e.shiftKey && (e.code === 'KeyN' || e.key?.toLowerCase() === 'n')) ||
          (e.code === 'Space' && !isTextEditing(e.target))) {
        e.preventDefault();
        setPendingNodePos(null);
        setQuickSearchPos({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
        setQuickSearchOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [view, history, handleSaveFlow, botSettingsOpen, pluginsModalOpen, quickSearchOpen]);

  const handlePaneContextMenu = (e, flowPos) => {
    setPendingNodePos(flowPos || null);
    // e may be either a native event or a plain {x,y} point from Canvas
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    const x = typeof e === 'object' && 'clientX' in e ? e.clientX : (e?.x ?? window.innerWidth / 2);
    const y = typeof e === 'object' && 'clientY' in e ? e.clientY : (e?.y ?? window.innerHeight / 2);
    setQuickSearchPos({ x, y });
    setQuickSearchOpen(true);
  };

  const handleDeleteBot = async (botId) => {
    const confirmMsg = t('common.confirm_delete_bot');
    if (window.confirm(confirmMsg)) {
      await api.deleteBot(botId);
      if (currentBot?.id === botId) {
        handleBackToDashboard();
      } else {
        loadBots();
      }
    }
  };

  const handleRefreshBot = async (bot) => {
    try {
      await api.refreshBotInfo(bot.id);
      await loadBots();
    } catch (e) {
      window.alert(e.message || t('common.error'));
    }
  };

  const handleUploadAvatar = async (bot, file) => {
    try {
      const res = await api.uploadBotAvatar(bot.id, file);
      await loadBots();
      return res;
    } catch (e) {
      window.alert(e.message || t('common.error'));
      throw e;
    }
  };

  // 1. Not Logged In -> Show Login Page
  if (!isAuthenticated) {
    return <LoginPage onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  // 2. Logged In -> Dashboard or Studio
  return (
    <div className="w-screen h-screen overflow-hidden bg-background text-foreground font-sans flex">
      {view === 'dashboard' ? (
        <>
          {/* Main Content Area */}
          {sidebarTab === 'profiles' && (
            <BotsList
              bots={bots}
              onSelectBot={handleSelectBot}
              onBotCreated={loadBots}
              onDeleteBot={handleDeleteBot}
              onRefreshBot={handleRefreshBot}
              onUploadAvatar={handleUploadAvatar}
            />
          )}

          {sidebarTab === 'plugins' && <PluginsView />}

          {sidebarTab === 'settings' && <SettingsView currentTheme={theme} onThemeChange={setTheme} />}

          {/* Right Sidebar (Profiles -> Plugins -> Settings) */}
          <Sidebar
            activeTab={sidebarTab}
            onTabChange={setSidebarTab}
            onLogout={handleLogout}
            collapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          />
        </>
      ) : (
        /* Full Visual Studio Canvas */
        <div className="w-full h-full relative">
          {/* Top Auto-Hide Navbar */}
          <Navbar
            currentBot={currentBot}
            allBots={bots}
            onSelectBot={handleSelectBot}
            onBackToDashboard={handleBackToDashboard}
            onSaveFlow={handleSaveFlow}
            isDirty={isDirty}
            isSaving={isSaving || !flowReady}
            onExportFlow={handleExportFlow}
            onImportFlow={handleImportFlow}
            onOpenPlugins={() => setPluginsModalOpen(true)}
            onOpenBotSettings={() => setBotSettingsOpen(true)}
            onToggleRunBot={handleToggleRunBot}
            updateInfo={updateInfo}
            theme={theme}
            setTheme={setTheme}
          />

          {/* Infinite DAG Canvas */}
          <div data-graph-editor className="w-full h-full">
          <Canvas
            onInit={instance => { flowInstance.current = instance; }}
            onNodeDragStart={beginDrag}
            onNodeDragStop={endDrag}
            onSelectionDragStart={beginDrag}
            onSelectionDragStop={endDrag}
            nodes={nodes}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={handleConnect}
            onNodeClick={handleNodeClick}
            onPaneContextMenu={handlePaneContextMenu}
            onAddNodeAt={handleAddNodeAt}
            onDeleteNode={handleDeleteNode}
            onDeleteEdge={handleDeleteEdge}
            theme={theme}
            dirty={isDirty}
          />
          </div>

          {/* Floating Draggable Resizable Telegram Mockup & Live Simulator */}
          <TelegramMockup
            currentBot={currentBot}
            selectedNode={selectedNode}
            edges={edges}
            onUpdateNodeData={handleUpdateNodeData}
            nodes={nodes}
          />

          {/* Quick Search Palette */}
          <QuickSearchPalette
            isOpen={quickSearchOpen}
            onClose={() => setQuickSearchOpen(false)}
            onSelectNode={handleAddNode}
            position={quickSearchPos}
            currentBot={currentBot}
          />

          {/* Plugins Modal */}
          <PluginsModal
            isOpen={pluginsModalOpen}
            onClose={() => setPluginsModalOpen(false)}
            currentBot={currentBot}
          />

          {/* Bot Settings Modal */}
          <BotSettingsModal
            isOpen={botSettingsOpen}
            onClose={() => setBotSettingsOpen(false)}
            bot={currentBot}
            onBotUpdated={handleUpdateBot}
            onExportFlow={handleExportFlow}
            onImportFlow={handleImportFlow}
          />
        </div>
      )}
    </div>
  );
}
