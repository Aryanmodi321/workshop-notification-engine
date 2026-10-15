import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bell,
  BellRing,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  Clock3,
  Copy,
  LayoutDashboard,
  ListFilter,
  Mail,
  Menu,
  RefreshCw,
  Search,
  X,
  XCircle,
} from 'lucide-react';
import FadeContent from './components/FadeContent.jsx';
import BlurText from './components/BlurText.tsx';
import SpotlightCard from './components/SpotlightCard.tsx';
import { API_BASE_URL } from './lib/api.ts';
import { useDashboardData } from './lib/useDashboardData.js';

const ROUTES = [
  { href: '/app', label: 'Overview', icon: LayoutDashboard },
  { href: '/app/workshops', label: 'Workshops', icon: CalendarDays },
  { href: '/app/notifications', label: 'Notifications', icon: BellRing },
];

const PAGE_COPY = {
  '/app': { title: 'Overview', subtitle: 'A live view of workshops and notification jobs returned by the API.' },
  '/app/workshops': { title: 'Workshops', subtitle: 'Browse workshop records available from the API.' },
  '/app/notifications': { title: 'Notifications', subtitle: 'Review notification job status and delivery fields from the API.' },
};

const STATUS_META = {
  sent: { label: 'Sent', className: 'status-sent', icon: Check },
  pending: { label: 'Pending', className: 'status-pending', icon: Clock3 },
  processing: { label: 'Processing', className: 'status-processing', icon: Activity },
  dead: { label: 'Dead', className: 'status-failed', icon: XCircle },
};

const metricIcons = { calendar: CalendarDays, bell: Bell, active: Check, pending: Clock3 };

function useRoute() {
  const [path, setPath] = useState(() => normalizePath(window.location.pathname));

  useEffect(() => {
    const onPopState = () => setPath(normalizePath(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigate = (href, event) => {
    if (event) event.preventDefault();
    window.history.pushState({}, '', href);
    setPath(normalizePath(href));
    window.scrollTo({ top: 0, behavior: 'auto' });
  };

  return [path, navigate];
}

function normalizePath(path) {
  if (path === '/app/workshops' || path === '/app/notifications' || path === '/app') return path;
  return path === '/' ? '/' : '/';
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = event => setReduced(event.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  return reduced;
}

function MotionSafeFade({ children, className = '' }) {
  const reducedMotion = useReducedMotion();
  if (reducedMotion) return <div className={className}>{children}</div>;
  return (
    <FadeContent className={className} duration={420} threshold={0.02} initialOpacity={0}>
      {children}
    </FadeContent>
  );
}

function App() {
  const [route, navigate] = useRoute();
  if (route === '/') return <LandingPage navigate={navigate} />;
  return <DashboardApp route={route} navigate={navigate} />;
}

function DashboardApp({ route, navigate }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [selectedJob, setSelectedJob] = useState(null);
  const [toast, setToast] = useState('');
  const data = useDashboardData();
  const page = PAGE_COPY[route];

  useEffect(() => {
    setMobileNavOpen(false);
  }, [route]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(''), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const notifyClipboardUnavailable = () => setToast('Clipboard access is unavailable in this browser.');

  const goTo = (href, event) => {
    navigate(href, event);
    setMobileNavOpen(false);
  };

  return (
    <div className="app-shell">
      {mobileNavOpen && <button aria-label="Close navigation" className="nav-scrim" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${mobileNavOpen ? 'sidebar-open' : ''}`}>
        <a className="brand" href="/app" onClick={event => goTo('/app', event)} aria-label="Relay overview">
          <span className="brand-mark"><BellRing size={19} strokeWidth={2.3} /></span>
          <span className="brand-copy"><strong>relay</strong><small>WORKSHOP OPS</small></span>
        </a>

        <div className="workspace-switcher">
          <div className="workspace-avatar">API</div>
          <div className="workspace-copy"><strong>Workshop API</strong><span>Read-only data</span></div>
        </div>

        <nav className="primary-nav" aria-label="Main navigation">
          <span className="nav-section-label">WORKSPACE</span>
          {ROUTES.map(({ href, label, icon: Icon }) => {
            const count = href === '/app/workshops' ? data.workshops.data?.length : href === '/app/notifications' ? data.jobs.data?.length : null;
            return (
            <a
              key={href}
              href={href}
              onClick={event => goTo(href, event)}
              className={`nav-link ${route === href ? 'nav-link-active' : ''}`}
              aria-current={route === href ? 'page' : undefined}
            >
              <Icon size={18} strokeWidth={1.9} />
              <span>{label}</span>
              {count !== null && count !== undefined && <span className="nav-count">{count}</span>}
            </a>
            );
          })}
        </nav>

        <div className="sidebar-spacer" />
        <div className="sidebar-help">
          <span className="help-icon"><CircleHelp size={17} /></span>
          <div><strong>Need a hand?</strong><small>Visit the help center</small></div>
          <ArrowUpRight size={15} className="muted-icon" />
        </div>
        <div className="profile-row">
          <div className="profile-avatar">RO</div>
          <div className="profile-copy"><strong>Read-only view</strong><span>No account connected</span></div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <button className="icon-button mobile-menu-button" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>
            <Menu size={20} />
          </button>
          <div className="breadcrumb"><span>Workspace</span><ChevronRight size={14} /><strong>{page.title}</strong></div>
          <div className="topbar-actions">
          <button className="global-search" onClick={() => goTo('/app/notifications')} aria-label="Open notification jobs search">
              <Search size={16} /><span>Search notification jobs...</span>
            </button>
            <span className="topbar-divider" />
            <button className="icon-button notification-button" aria-label="View notifications" onClick={() => goTo('/app/notifications')}>
              <Bell size={18} /><i />
            </button>
            <span className="topbar-avatar" aria-label="Read-only view">RO</span>
          </div>
        </header>

        <main className="page-wrap">
          <div className="page-heading">
            <div>
              <div className="eyebrow"><span className="eyebrow-dot" /> OPERATIONS</div>
              <h1>{page.title}</h1>
              <p>{page.subtitle}</p>
            </div>
            <button className="button button-primary" onClick={data.refresh} disabled={data.workshops.loading || data.jobs.loading}><RefreshCw size={16} /> Refresh data</button>
          </div>

          <div className={`demo-notice ${data.workshops.error || data.jobs.error ? 'notice-error' : ''}`} role="status" aria-live="polite">
            <span className="demo-dot" />
            <span><strong>{data.workshops.loading || data.jobs.loading ? 'Connecting to API' : data.workshops.error || data.jobs.error ? 'API data unavailable' : 'API responses loaded'}</strong> Base URL: <code>{API_BASE_URL}</code></span>
            <span className="health-summary">API {healthLabel(data.health)} · DB {healthLabel(data.databaseHealth)}</span>
          </div>

          <MotionSafeFade className="page-entrance">
            {route === '/app' && <OverviewPage workshops={data.workshops} jobs={data.jobs} onSelectJob={job => { setSelectedJob(job); navigate('/app/notifications'); }} onNavigate={goTo} />}
            {route === '/app/workshops' && <WorkshopsPage resource={data.workshops} onRefresh={data.refresh} />}
            {route === '/app/notifications' && <NotificationsPage resource={data.jobs} selectedJob={selectedJob} onSelectJob={setSelectedJob} onNotify={notifyClipboardUnavailable} onRefresh={data.refresh} />}
          </MotionSafeFade>
          <footer className="page-footer"><span>Relay Workspace</span><span>Read-only dashboard <i /> GET endpoints only</span></footer>
        </main>
      </div>
      {toast && <div className="toast" role="status"><CheckCheck size={17} />{toast}<button aria-label="Dismiss message" onClick={() => setToast('')}><X size={15} /></button></div>}
    </div>
  );
}

function LandingPage({ navigate }) {
  const reducedMotion = useReducedMotion();
  const enterDashboard = event => navigate('/app', event);
  const capabilities = [
    { number: '01', title: 'Registration with a durable handoff', copy: 'A successful registration and its confirmation job are saved together through the transactional outbox.' },
    { number: '02', title: 'Independent notification jobs', copy: 'Each job has its own status and bounded retry lifecycle, so one transient failure does not block the rest.' },
    { number: '03', title: 'Cancellation fan-out', copy: 'Workshop cancellation creates a separate notification job for each registered member.' },
  ];
  return (
    <div className="landing-shell">
      <header className="landing-nav">
        <a className="landing-brand" href="/" onClick={event => navigate('/', event)} aria-label="Relay home"><span className="brand-mark"><BellRing size={19} /></span><span><strong>relay</strong><small>WORKSHOP OPS</small></span></a>
        <nav aria-label="Public navigation"><a href="#capabilities">Capabilities</a><a href="#workflow">How it works</a></nav>
        <a className="button button-primary landing-nav-cta" href="/app" onClick={enterDashboard}>Open dashboard <ArrowRight size={16} /></a>
      </header>

      <main>
        <section className="landing-hero">
          <div className="hero-glow" aria-hidden="true" />
          <div className="hero-copy">
            <span className="landing-kicker"><i /> WORKSHOP REGISTRATION &amp; NOTIFICATIONS</span>
            {reducedMotion ? <h1>Workshop operations,<br /><em>in clear view.</em></h1> : <div className="hero-title"><BlurText text="Workshop operations, in clear view." animateBy="words" delay={90} className="hero-animated-title" /></div>}
            <p>Relay gives your team a clear view of workshop records and the notification jobs behind every registration and cancellation.</p>
            <div className="hero-actions"><a className="button button-primary button-large" href="/app" onClick={enterDashboard}>Explore the dashboard <ArrowRight size={17} /></a><a className="hero-secondary-link" href="#workflow">See how it works <ChevronRight size={16} /></a></div>
            <div className="hero-proof"><span><Check size={14} /> Durable job handoff</span><span><Check size={14} /> Bounded retries</span><span><Check size={14} /> Read-only dashboard</span></div>
          </div>
          <SpotlightCard className="landing-preview" spotlightColor="rgba(112, 137, 255, 0.2)">
            <div className="preview-top"><div><span className="preview-overline">WORKSPACE PREVIEW</span><strong>Workshop operations</strong></div><span className="preview-live"><i /> API CONNECTED WHEN CONFIGURED</span></div>
            <div className="preview-content">
              <div className="preview-side"><span className="preview-logo"><BellRing size={13} /></span><i /><i /><i /></div>
              <div className="preview-main"><div className="preview-heading"><div><span>OVERVIEW</span><strong>Your operations</strong></div><span className="preview-date">Live API values</span></div>
                <div className="preview-metrics"><div><span>Workshops</span><b>—</b><small>Loaded from API</small></div><div><span>Notification jobs</span><b>—</b><small>Loaded from API</small></div><div><span>API status</span><b className="preview-status">●</b><small>Connection check</small></div></div>
                <div className="preview-list"><div className="preview-list-head"><strong>Notification queue</strong><span>GET /notification-jobs</span></div><div className="preview-row"><i className="preview-dot pending"/><span>Confirmation job</span><code>pending</code></div><div className="preview-row"><i className="preview-dot sent"/><span>Cancellation job</span><code>sent</code></div></div>
                <div className="preview-caption">Illustrative interface only · live records appear in the dashboard</div>
              </div>
            </div>
          </SpotlightCard>
          <div className="hero-orbit orbit-one" aria-hidden="true" /><div className="hero-orbit orbit-two" aria-hidden="true" />
        </section>

        <section className="landing-section capabilities-section" id="capabilities">
          <div className="landing-section-heading"><span className="section-kicker">BUILT AROUND THE WORKFLOW</span><h2>Every registration has a clear next step.</h2><p>Workshop records and notification delivery stay connected, even when a service needs another attempt.</p></div>
          <div className="capability-grid">{capabilities.map(item => <article className="capability-card" key={item.number}><span className="capability-number">{item.number}</span><div className="capability-icon">{item.number === '01' ? <CalendarDays /> : item.number === '02' ? <RefreshCw /> : <BellRing />}</div><h3>{item.title}</h3><p>{item.copy}</p></article>)}</div>
        </section>

        <section className="workflow-section" id="workflow"><div className="workflow-inner"><div className="workflow-intro"><span className="section-kicker">HOW RELAY WORKS</span><h2>From registration to delivery, without losing the thread.</h2><p>The dashboard reads current API records. The backend handles persistence and delivery attempts.</p><a className="text-link" href="/app" onClick={enterDashboard}>View operations <ArrowRight size={15} /></a></div><div className="workflow-steps"><div><span>01</span><section><strong>Register</strong><p>A member registration and its confirmation job are committed together.</p></section></div><div><span>02</span><section><strong>Process independently</strong><p>A worker picks up each durable job without holding the registration request open for delivery.</p></section></div><div><span>03</span><section><strong>Retry transient issues</strong><p>Temporary delivery failures are retried within the configured attempt limit.</p></section></div><div><span>04</span><section><strong>Fan out cancellations</strong><p>Cancellation creates an independent job for every registered member.</p></section></div></div></div></section>

        <section className="landing-cta"><div><span className="section-kicker">READY TO TAKE A LOOK?</span><h2>See the live operations view.</h2><p>Open the dashboard to inspect workshops, notification jobs and API health.</p></div><a className="button button-primary button-large" href="/app" onClick={enterDashboard}>Open dashboard <ArrowRight size={17} /></a></section>
      </main>
      <footer className="landing-footer"><a className="landing-brand" href="/" onClick={event => navigate('/', event)}><span className="brand-mark"><BellRing size={17} /></span><span><strong>relay</strong><small>WORKSHOP OPS</small></span></a><span>Workshop operations, clearly connected.</span><a href="/app" onClick={enterDashboard}>Dashboard <ArrowUpRight size={14} /></a></footer>
    </div>
  );
}

function healthLabel(resource) {
  if (resource.loading) return 'checking';
  if (resource.error) return 'unavailable';
  return resource.data?.status || 'unknown';
}

function OverviewPage({ workshops, jobs, onSelectJob, onNavigate }) {
  const workshopRows = workshops.data || [];
  const jobRows = jobs.data || [];
  const recentJobs = [...jobRows].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 5);
  const summary = [
    { label: 'Workshops returned', value: workshops.data?.length, detail: 'GET /workshops', icon: 'calendar', tone: 'blue' },
    { label: 'Active workshops', value: workshops.data ? workshopRows.filter(item => item.status === 'active').length : null, detail: 'Current API records', icon: 'active', tone: 'violet' },
    { label: 'Notification jobs', value: jobs.data?.length, detail: 'GET /notification-jobs', icon: 'bell', tone: 'amber' },
    { label: 'Pending / processing', value: jobs.data ? jobRows.filter(item => item.status === 'pending' || item.status === 'processing').length : null, detail: 'Open notification jobs', icon: 'pending', tone: 'green' },
  ];
  return (
    <>
      <section className="metric-grid" aria-label="Workspace summary">
        {summary.map(metric => {
          const Icon = metricIcons[metric.icon];
          return <article className="metric-card" key={metric.label}>
            <div className="metric-top"><span>{metric.label}</span><span className={`metric-icon metric-${metric.tone}`}><Icon size={18} /></span></div>
            <strong className="metric-value">{workshops.loading || jobs.loading ? '…' : metric.value ?? '—'}</strong>
            <div className="metric-foot"><span>{metric.detail}</span></div>
          </article>;
        })}
      </section>

      <section className="overview-grid">
        <article className="card activity-card">
          <div className="card-header">
            <div><h2>Registration activity</h2><p>Not exposed by the current read API</p></div>
            <span className="tiny-demo-tag">UNAVAILABLE</span>
          </div>
          <div className="unavailable-panel"><Activity size={22} /><strong>Registration counts are not available</strong><span>The API has no registration listing or aggregate endpoint.</span></div>
        </article>

        <article className="card delivery-card">
          <div className="card-header"><div><h2>Job status</h2><p>Counts from returned notification jobs</p></div></div>
          <div className="health-list">
            {['pending', 'processing', 'sent', 'dead'].map(status => <div key={status}><span className="health-label"><i className={`health-dot ${status}-dot`} /> {statusLabel(status)}</span><strong>{jobs.loading ? '…' : jobRows.filter(job => job.status === status).length}</strong></div>)}
          </div>
          <button className="text-link" onClick={() => onNavigate('/notifications')}>View notification queue <ArrowRight size={15} /></button>
        </article>
      </section>

      <section className="card table-card">
          <div className="card-header table-card-header">
          <div><div className="title-with-tag"><h2>Recent notifications</h2></div><p>Latest jobs returned by the API</p></div>
          <button className="button button-secondary" onClick={() => onNavigate('/notifications')}>View all <ArrowRight size={15} /></button>
        </div>
        {jobs.error ? <ResourceMessage resource={jobs} label="Notification jobs" /> : jobs.loading ? <ResourceMessage resource={jobs} label="Notification jobs" /> : recentJobs.length === 0 ? <EmptyState title="No notification jobs" message="The API returned an empty job list." /> : <NotificationTable jobs={recentJobs} onSelect={onSelectJob} compact />}
      </section>
    </>
  );
}

function WorkshopsPage({ resource, onRefresh }) {
  const [filter, setFilter] = useState('All workshops');
  const [search, setSearch] = useState('');
  const workshops = resource.data || [];
  const filters = [
    { label: 'All workshops', matches: () => true },
    { label: 'Active', matches: workshop => workshop.status === 'active' },
    { label: 'Cancelled', matches: workshop => workshop.status === 'cancelled' },
  ];
  const visible = workshops.filter(workshop => {
    const selectedFilter = filters.find(item => item.label === filter);
    const matchesSearch = `${workshop.title} ${workshop.description} ${workshop.id}`.toLowerCase().includes(search.toLowerCase());
    return selectedFilter.matches(workshop) && matchesSearch;
  });

  return (
    <>
      <div className="section-toolbar">
        <div className="segmented-control" role="tablist" aria-label="Filter workshops">
          {filters.map(item => <button key={item.label} className={filter === item.label ? 'segment-active' : ''} onClick={() => setFilter(item.label)} role="tab" aria-selected={filter === item.label}>{item.label}<span>{resource.loading ? '…' : workshops.filter(item.matches).length}</span></button>)}
        </div>
        <div className="toolbar-actions"><label className="search-field"><Search size={16} /><input aria-label="Search workshops" placeholder="Search workshops" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
      </div>

      <div className="workshop-summary"><span>Showing <strong>{resource.loading ? '…' : visible.length}</strong> of {resource.loading ? '…' : workshops.length} API workshops</span><span className="sort-button">Order: API response</span></div>
      <section className="card table-card">
        {resource.error || resource.loading ? <ResourceMessage resource={resource} label="Workshops" /> : workshops.length === 0 ? <EmptyState title="No workshops" message="The API returned an empty workshop list." /> : visible.length === 0 ? <EmptyState title="No workshops found" message="Try a different title or status filter." /> : <div className="workshop-table-wrap"><table className="data-table workshop-table">
          <thead><tr><th>Workshop</th><th>Scheduled</th><th>Description</th><th>Status</th></tr></thead>
          <tbody>{visible.map(workshop => (
            <tr key={workshop.id}>
              <td><div className="workshop-cell"><span className="workshop-avatar avatar-blue"><CalendarDays size={16} /></span><div><strong>{workshop.title}</strong><small>Workshop #{workshop.id}</small></div></div></td>
              <td><strong className="table-primary-text">{formatDate(workshop.scheduled_at, { dateStyle: 'medium' })}</strong><small className="table-secondary-text">{formatDate(workshop.scheduled_at, { timeStyle: 'short' })}</small></td>
              <td><span className="workshop-description">{workshop.description || 'No description provided'}</span></td>
              <td><WorkshopStatus status={workshop.status} /></td>
            </tr>
          ))}</tbody>
        </table></div>}
        {!resource.loading && !resource.error && workshops.length > 0 && <ResultsFooter total={visible.length} />}
        {resource.error && <button className="button button-secondary resource-retry" onClick={onRefresh}><RefreshCw size={15} /> Retry</button>}
      </section>
    </>
  );
}

function NotificationsPage({ resource, selectedJob, onSelectJob, onNotify, onRefresh }) {
  const [statusFilter, setStatusFilter] = useState('All jobs');
  const [search, setSearch] = useState('');
  const [panelOpen, setPanelOpen] = useState(Boolean(selectedJob));
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const jobs = resource.data || [];
  const tabs = [
    { label: 'All jobs', key: 'all', matches: () => true },
    { label: 'Pending', key: 'pending', matches: job => job.status === 'pending' },
    { label: 'Processing', key: 'processing', matches: job => job.status === 'processing' },
    { label: 'Sent', key: 'sent', matches: job => job.status === 'sent' },
    { label: 'Dead', key: 'dead', matches: job => job.status === 'dead' },
  ];
  const filteredJobs = useMemo(() => [...jobs]
    .filter(job => tabs.find(tab => tab.label === statusFilter).matches(job))
    .filter(job => `${job.id} ${job.recipient} ${job.event_type} ${job.status}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)), [jobs, search, statusFilter]);

  const selectJob = job => {
    onSelectJob(job);
    setPanelOpen(true);
  };

  return (
    <div className={`notification-layout ${panelOpen ? 'details-open' : ''}`}>
      <section className="card notification-list-card">
        <div className="notification-toolbar">
          <div className="notification-tabs" role="tablist" aria-label="Filter notifications by status">
            {tabs.map(tab => <button key={tab.key} className={statusFilter === tab.label ? 'notification-tab-active' : ''} onClick={() => setStatusFilter(tab.label)} role="tab" aria-selected={statusFilter === tab.label}>{tab.label}<span>{resource.loading ? '…' : jobs.filter(tab.matches).length}</span></button>)}
          </div>
          <div className="notification-tools"><label className="search-field notification-search"><Search size={16} /><input aria-label="Search notification jobs" placeholder="Search jobs..." value={search} onChange={event => setSearch(event.target.value)} /></label><button className="icon-button mobile-filter-button" aria-label="Show filters" onClick={() => setMobileFiltersOpen(!mobileFiltersOpen)}><ListFilter size={17} /></button></div>
        </div>
        {mobileFiltersOpen && <div className="mobile-filter-panel"><span>Filter by status</span><select value={statusFilter} onChange={event => setStatusFilter(event.target.value)}>{tabs.map(tab => <option key={tab.key}>{tab.label}</option>)}</select></div>}
        {resource.error || resource.loading ? <ResourceMessage resource={resource} label="Notification jobs" /> : jobs.length === 0 ? <EmptyState title="No notification jobs" message="The API returned an empty job list." /> : filteredJobs.length === 0 ? <EmptyState title="No matching jobs" message="Try another search or status filter." /> : <div className="notification-table-wrap"><NotificationTable jobs={filteredJobs} onSelect={selectJob} selectedId={selectedJob?.id} /></div>}
        {!resource.loading && !resource.error && jobs.length > 0 && <ResultsFooter total={filteredJobs.length} />}
        {resource.error && <button className="button button-secondary resource-retry" onClick={onRefresh}><RefreshCw size={15} /> Retry</button>}
      </section>
      {panelOpen && <button aria-label="Close job details" className="details-scrim" onClick={() => setPanelOpen(false)} />}
      <JobDetails job={selectedJob} open={panelOpen} onClose={() => setPanelOpen(false)} onNotify={onNotify} />
    </div>
  );
}

function NotificationTable({ jobs, onSelect, selectedId, compact = false }) {
  return (
    <div className={`notification-table-outer ${compact ? 'notification-compact' : ''}`}>
      <table className="data-table notification-table">
        <thead><tr><th>Notification</th><th>Recipient</th><th>Status</th><th>Attempts</th><th>Created</th><th aria-label="Details" /></tr></thead>
        <tbody>{jobs.map(job => (
          <tr key={job.id} className={selectedId === job.id ? 'selected-row' : ''} onClick={() => onSelect(job)} tabIndex={0} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(job); } }}>
            <td><div className="notification-name"><span className={`event-icon ${job.event_type === 'workshop_cancelled' ? 'event-cancel' : 'event-confirm'}`}>{job.event_type === 'workshop_cancelled' ? <XCircle size={16} /> : <Mail size={16} />}</span><div><strong>{eventLabel(job.event_type)}</strong><small><code>Job #{job.id}</code></small></div></div></td>
            <td><span className="recipient-cell">{job.recipient}</span></td>
            <td><StatusBadge status={job.status} /></td>
            <td><span className={`attempt-count ${job.attempt_count > 1 ? 'attempt-warn' : ''}`}>{job.attempt_count}</span></td>
            <td><span className="created-cell">{formatDate(job.created_at, { dateStyle: 'medium', timeStyle: 'short' })}</span></td>
            <td><button className="row-action" aria-label={`View job ${job.id} details`} onClick={event => { event.stopPropagation(); onSelect(job); }}><ChevronRight size={17} /></button></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }) {
  const meta = STATUS_META[status] || STATUS_META.pending;
  const Icon = meta.icon;
  return <span className={`status-badge ${meta.className}`}><Icon size={13} strokeWidth={2.2} />{meta.label}</span>;
}

function WorkshopStatus({ status }) {
  const classes = status === 'cancelled' ? 'status-cancelled' : 'status-active';
  return <span className={`workshop-status ${classes}`}><i />{statusLabel(status)}</span>;
}

function ResultsFooter({ total }) {
  return <div className="pagination"><span>Showing <strong>{total}</strong> results from the API response</span></div>;
}

function ResourceMessage({ resource, label }) {
  return <div className={`resource-message ${resource.error ? 'resource-error' : ''}`} role={resource.error ? 'alert' : 'status'}>
    {resource.error ? <><strong>Could not load {label.toLowerCase()}</strong><span>{resource.error}</span></> : <><span className="loading-spinner" /><strong>Loading {label.toLowerCase()}…</strong></>}
  </div>;
}

function EmptyState({ title, message }) {
  return <div className="empty-state"><Search size={20} /><strong>{title}</strong><span>{message}</span></div>;
}

function statusLabel(status) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function eventLabel(eventType) {
  if (eventType === 'registration_confirmation') return 'Registration confirmation';
  if (eventType === 'workshop_cancelled') return 'Workshop cancellation';
  return eventType.replaceAll('_', ' ');
}

function formatDate(value, options) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, { ...options, timeZone: 'UTC' }).format(date);
}

function JobDetails({ job, open, onClose, onNotify }) {
  const [copied, setCopied] = useState(false);
  if (!job) return null;
  const key = `notification-job-${job.id}`;

  const copy = async value => {
    try {
      await navigator.clipboard.writeText(String(value));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      onNotify();
    }
  };

  return (
    <aside className={`details-panel ${open ? 'details-panel-open' : ''}`} aria-label="Notification job details" aria-hidden={!open}>
      <div className="details-header"><div><span className="panel-kicker">JOB DETAILS</span><h2>Job #{job.id}</h2></div><button className="icon-button" aria-label="Close details panel" onClick={onClose}><X size={18} /></button></div>
      <div className="details-job-id"><code>{job.id}</code><button aria-label="Copy job ID" onClick={() => copy(job.id)}><Copy size={14} /></button></div>
      <div className="details-status-line"><StatusBadge status={job.status} /><span>Created {formatDate(job.created_at, { dateStyle: 'medium', timeStyle: 'short' })}</span></div>
      <div className="details-divider" />
      <section className="details-section"><h3>Message</h3><div className="detail-field"><span>Event type</span><strong>{eventLabel(job.event_type)}</strong></div><div className="detail-field"><span>Recipient</span><strong>{job.recipient}</strong></div></section>
      <div className="details-divider" />
      <section className="details-section"><h3>Delivery</h3><div className="detail-field"><span>Attempts</span><strong>{job.attempt_count}</strong></div>{job.status === 'pending' && <div className="detail-field"><span>Next attempt</span><strong>{formatDate(job.next_attempt_at, { dateStyle: 'medium', timeStyle: 'short' })}</strong></div>}{job.sent_at && <div className="detail-field"><span>Sent</span><strong>{formatDate(job.sent_at, { dateStyle: 'medium', timeStyle: 'short' })}</strong></div>}{job.last_error && <div className="error-callout"><XCircle size={15} /><div><strong>Last attempt failed</strong><span>{job.last_error}</span></div></div>}</section>
      <div className="details-divider" />
      <section className="details-section"><div className="idempotency-heading"><h3>Idempotency key</h3><span>STABLE</span></div><div className="key-box"><code>{key}</code><button aria-label="Copy idempotency key" onClick={() => copy(key)}>{copied ? <Check size={14} /> : <Copy size={14} />}</button></div><p className="detail-helper">Stable for retries of this notification job.</p></section>
      <div className="details-panel-note"><span className="demo-dot" /><span>Fields returned by the API</span></div>
    </aside>
  );
}

export default App;
