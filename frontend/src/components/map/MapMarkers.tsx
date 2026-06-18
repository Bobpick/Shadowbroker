import React from 'react';
import { Marker } from 'react-map-gl/maplibre';
import type { Earthquake, SelectedEntity, Ship, TrackedFlight, UAV } from '@/types/dashboard';
import type { SpreadAlertItem } from '@/utils/alertSpread';
import { REDDIT_MARKER_OFFSET, TELEGRAM_MARKER_OFFSET } from '@/components/map/geoJSONBuilders';

// Shared monospace label style base
const LABEL_BASE: React.CSSProperties = {
  fontFamily: 'monospace',
  fontWeight: 'bold',
  textShadow: '0 0 3px #000, 0 0 3px #000',
  pointerEvents: 'none',
};

const LABEL_SHADOW_EXTRA = '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000';

// -- Cluster count label (ships / earthquakes) --
type ClusterPoint = {
  id: string | number;
  lat: number;
  lng: number;
  count: string | number;
};

export function ClusterCountLabels({ clusters, prefix }: { clusters: ClusterPoint[]; prefix: string }) {
  return (
    <>
      {clusters.map((c) => (
        <Marker
          key={`${prefix}-${c.id}`}
          longitude={c.lng}
          latitude={c.lat}
          anchor="center"
          style={{ zIndex: 1 }}
        >
          <div style={{ ...LABEL_BASE, color: '#fff', fontSize: '11px', textAlign: 'center' }}>
            {c.count}
          </div>
        </Marker>
      ))}
    </>
  );
}

// -- Tracked flights labels --
const TRACKED_LABEL_COLOR_MAP: Record<string, string> = {
  '#ff1493': '#ff1493',
  pink: '#ff1493',
  red: '#ff4444',
  blue: '#3b82f6',
  orange: '#FF8C00',
  '#32cd32': '#32cd32',
  purple: '#b266ff',
  white: '#cccccc',
};

interface TrackedFlightLabelsProps {
  flights: TrackedFlight[];
  zoom: number;
  inView: (lat: number, lng: number) => boolean;
  interpFlight: (f: TrackedFlight) => [number, number];
}

export function TrackedFlightLabels({
  flights,
  zoom,
  inView,
  interpFlight,
}: TrackedFlightLabelsProps) {
  return (
    <>
      {flights.map((f, i) => {
        if (f.lat == null || f.lng == null) return null;
        if (!inView(f.lat, f.lng)) return null;

        const alertColor = f.alert_color || '#ff1493';
        if (alertColor === 'yellow' || alertColor === 'black') return null;

        const isHighPriority =
          alertColor === '#ff1493' || alertColor === 'pink' || alertColor === 'red';
        if (!isHighPriority && zoom < 5) return null;

        const displayName =
          f.alert_operator ||
          f.operator ||
          f.owner ||
          f.name ||
          f.callsign ||
          f.icao24 ||
          'UNKNOWN';
        if (displayName === 'Private' || displayName === 'private') return null;

        const grounded = f.alt != null && f.alt <= 100;
        const labelColor = grounded ? '#888' : TRACKED_LABEL_COLOR_MAP[alertColor] || alertColor;
        const [iLng, iLat] = interpFlight(f);

        return (
          <Marker
            key={`tf-label-${i}`}
            longitude={iLng}
            latitude={iLat}
            anchor="top"
            offset={[0, 10]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: labelColor,
                fontSize: `${Math.max(10, Math.min(16, 10 + (zoom - 5) * 1.2))}px`,
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
              {String(displayName)}
            </div>
          </Marker>
        );
      })}
    </>
  );
}

// -- Carrier labels --
interface CarrierLabelsProps {
  ships: Ship[];
  inView: (lat: number, lng: number) => boolean;
  interpShip: (s: Ship) => [number, number];
}

export function CarrierLabels({ ships, inView, interpShip }: CarrierLabelsProps) {
  return (
    <>
      {ships.map((s, i) => {
        if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
        if (!inView(s.lat, s.lng)) return null;
        const [iLng, iLat] = interpShip(s);
        return (
          <Marker
            key={`carrier-label-${i}`}
            longitude={iLng}
            latitude={iLat}
            anchor="top"
            offset={[0, 12]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
                textAlign: 'center',
              }}
            >
              <div style={{ color: '#ffaa00', fontSize: '11px', fontWeight: 'bold' }}>
                [[{s.name}]]
              </div>
              {s.estimated && (
                <div style={{ color: '#ff6644', fontSize: '8px', letterSpacing: '1.5px' }}>
                  EST. POSITION — OSINT
                </div>
              )}
            </div>
          </Marker>
        );
      })}
    </>
  );
}

// -- Tracked yacht labels --
interface TrackedYachtLabelsProps {
  ships: Ship[];
  inView: (lat: number, lng: number) => boolean;
  interpShip: (s: Ship) => [number, number];
}

export function TrackedYachtLabels({ ships, inView, interpShip }: TrackedYachtLabelsProps) {
  return (
    <>
      {ships.map((s, i) => {
        if (!s.yacht_alert || s.lat == null || s.lng == null) return null;
        if (!inView(s.lat, s.lng)) return null;
        const [iLng, iLat] = interpShip(s);
        return (
          <Marker
            key={`yacht-label-${i}`}
            longitude={iLng}
            latitude={iLat}
            anchor="top"
            offset={[0, 12]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: s.yacht_color || '#FF69B4',
                fontSize: '10px',
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
              {s.yacht_owner || s.name || 'TRACKED YACHT'}
            </div>
          </Marker>
        );
      })}
    </>
  );
}

// -- UAV labels --
interface UavLabelsProps {
  uavs: UAV[];
  inView: (lat: number, lng: number) => boolean;
  zoom?: number;
}

export function UavLabels({ uavs, inView, zoom = 5 }: UavLabelsProps) {
  const labelSize = `${Math.max(10, Math.min(16, 10 + (zoom - 5) * 1.2))}px`;
  return (
    <>
      {uavs.map((uav, i) => {
        if (uav.lat == null || uav.lng == null) return null;
        if (!inView(uav.lat, uav.lng)) return null;
        const name = uav.aircraft_model ? `[UAV: ${uav.aircraft_model}]` : `[UAV: ${uav.callsign}]`;
        return (
          <Marker
            key={`uav-label-${i}`}
            longitude={uav.lng}
            latitude={uav.lat}
            anchor="top"
            offset={[0, 10]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: '#ff8c00',
                fontSize: labelSize,
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
              {name}
            </div>
          </Marker>
        );
      })}
    </>
  );
}

// -- Earthquake labels --
interface EarthquakeLabelsProps {
  earthquakes: Earthquake[];
  inView: (lat: number, lng: number) => boolean;
}

export function EarthquakeLabels({ earthquakes, inView }: EarthquakeLabelsProps) {
  return (
    <>
      {earthquakes.map((eq, i) => {
        if (eq.lat == null || eq.lng == null) return null;
        if (!inView(eq.lat, eq.lng)) return null;
        return (
          <Marker
            key={`eq-label-${i}`}
            longitude={eq.lng}
            latitude={eq.lat}
            anchor="top"
            offset={[0, 14]}
            style={{ zIndex: 1 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: '#ffcc00',
                fontSize: '10px',
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
              [M{eq.mag}] {eq.place || ''}
            </div>
          </Marker>
        );
      })}
    </>
  );
}

// -- Threat alert markers --
function getRiskColor(score: number): string {
  if (score >= 9) return '#ef4444';
  if (score >= 7) return '#f97316';
  if (score >= 4) return '#eab308';
  if (score >= 1) return '#3b82f6';
  return '#22c55e';
}

interface ThreatMarkerProps {
  spreadAlerts: SpreadAlertItem[];
  zoom: number;
  selectedEntity: SelectedEntity | null;
  onEntityClick?: (entity: SelectedEntity | null) => void;
  onDismiss?: (alertKey: string) => void;
}

export function ThreatMarkers({
  spreadAlerts,
  zoom,
  selectedEntity,
  onEntityClick,
  onDismiss,
}: ThreatMarkerProps) {
  return (
    <>
      {spreadAlerts.map((n) => {
        const count = n.cluster_count || 1;
        const score = n.risk_score || 0;
        const riskColor = getRiskColor(score);
        const alertKey = n.alertKey || `${n.title}|${n.coords?.[0]},${n.coords?.[1]}`;

        // Color-blind accessible border pattern based on severity
        const threatBorderClass =
          score >= 9 ? 'threat-border-critical' :
          score >= 7 ? 'threat-border-high' :
          score >= 4 ? 'threat-border-medium' :
                       'threat-border-low';

        let isVisible = zoom >= 1;
        if (selectedEntity) {
          if (selectedEntity.type === 'news') {
            if (selectedEntity.id !== alertKey) isVisible = false;
          } else {
            isVisible = false;
          }
        }

        return (
          <Marker
            key={`threat-${alertKey}`}
            longitude={n.coords[1]}
            latitude={n.coords[0]}
            anchor="center"
            offset={[n.offsetX, n.offsetY]}
            style={{ zIndex: 50 + score }}
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              onEntityClick?.({ id: alertKey, type: 'news' });
            }}
          >
            <div className="relative group/alert">
              {n.showLine && isVisible && (
                <svg
                  className="absolute pointer-events-none"
                  style={{
                    left: '50%',
                    top: '50%',
                    width: 1,
                    height: 1,
                    overflow: 'visible',
                    zIndex: -1,
                  }}
                >
                  <line
                    x1={0}
                    y1={0}
                    x2={-n.offsetX}
                    y2={-n.offsetY}
                    stroke={riskColor}
                    strokeWidth="1.5"
                    strokeDasharray="3,3"
                    className="opacity-80"
                  />
                  <circle cx={-n.offsetX} cy={-n.offsetY} r="2" fill={riskColor} />
                </svg>
              )}

              <div
                className={`cursor-pointer transition-opacity duration-300 relative ${threatBorderClass}`}
                style={{
                  opacity: isVisible ? 1.0 : 0.0,
                  pointerEvents: isVisible ? 'auto' : 'none',
                  backgroundColor: 'rgba(5, 5, 5, 0.96)',
                  borderColor: riskColor,
                  borderRadius: '4px',
                  padding: '8px 20px 8px 12px',
                  color: riskColor,
                  fontFamily: 'var(--font-jetbrains-mono), monospace',
                  fontSize: '12px',
                  fontWeight: 'bold',
                  textAlign: 'center',
                  zIndex: 10,
                  lineHeight: '1.3',
                  minWidth: '200px',
                }}
              >
                {n.showLine && isVisible && (
                  <div
                    className="absolute"
                    style={{
                      width: 0,
                      height: 0,
                      borderLeft: '6px solid transparent',
                      borderRight: '6px solid transparent',
                      borderTop: n.offsetY < 0 ? `6px solid ${riskColor}` : 'none',
                      borderBottom: n.offsetY > 0 ? `6px solid ${riskColor}` : 'none',
                      left: '50%',
                      [n.offsetY < 0 ? 'bottom' : 'top']: '-6px',
                      transform: 'translateX(-50%)',
                    }}
                  />
                )}

                <div
                  className="absolute inset-0 border border-current rounded opacity-50"
                  style={{ color: riskColor, zIndex: -1 }}
                ></div>
                {onDismiss && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDismiss(alertKey);
                    }}
                    style={{
                      position: 'absolute',
                      top: '4px',
                      right: '6px',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      color: riskColor,
                      fontSize: '16px',
                      fontWeight: 'bold',
                      lineHeight: 1,
                      padding: '0 2px',
                      opacity: 0.7,
                      zIndex: 20,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                    onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.7')}
                  >
                    ×
                  </button>
                )}
                <div style={{ fontSize: '14px', letterSpacing: '1.5px', textTransform: 'uppercase' as const }}>
                  !! ALERT LVL {score} !!
                </div>
                <div
                  style={{
                    color: '#fff',
                    fontSize: '12px',
                    marginTop: '4px',
                    maxWidth: '260px',
                    lineHeight: '1.4',
                  }}
                >
                  {n.title}
                </div>
                {count > 1 && (
                  <div
                    style={{ color: riskColor, opacity: 0.9, fontSize: '10px', marginTop: '4px', letterSpacing: '0.5px' }}
                  >
                    [+{count - 1} ACTIVE THREATS IN AREA]
                  </div>
                )}
              </div>
            </div>
          </Marker>
        );
      })}
    </>
  );
}

function OsintPostCountBadge({ count }: { count: number }) {
  if (count <= 1) return null;
  return (
    <span
      style={{
        position: 'absolute',
        top: -5,
        right: -6,
        minWidth: 14,
        height: 14,
        padding: '0 3px',
        borderRadius: 7,
        background: '#0f172a',
        border: '1.5px solid rgba(255,255,255,0.35)',
        color: '#f8fafc',
        fontFamily: 'monospace',
        fontSize: 9,
        fontWeight: 700,
        lineHeight: '11px',
        textAlign: 'center',
        pointerEvents: 'none',
      }}
    >
      {count > 99 ? '99+' : count}
    </span>
  );
}

/** Red broadcast disc — circle + radio waves (not a plain dot). */
function TelegramOsintPin({ size }: { size: number }) {
  const iconSize = Math.max(10, Math.round(size * 0.68));
  return (
    <div
      style={{
        position: 'relative',
        width: size,
        height: size,
        borderRadius: '50%',
        background: '#ef4444',
        border: '2.5px solid #fca5a5',
        boxShadow: '0 0 14px rgba(239, 68, 68, 0.75)',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <svg
        width={iconSize}
        height={iconSize}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="2.25" fill="#fff" />
        <path
          d="M12 5a7 7 0 0 1 0 14M12 8a4 4 0 0 1 0 8"
          stroke="#fff"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}

/** Orange rounded square with “r” — visually distinct from Telegram circles. */
function RedditOsintPin({
  size,
  adversarial,
  protest,
}: {
  size: number;
  adversarial: boolean;
  protest: boolean;
}) {
  const fontSize = Math.max(11, Math.round(size * 0.58));
  const protestStyle = protest && !adversarial;
  return (
    <div
      style={{
        position: 'relative',
        width: size,
        height: size,
        borderRadius: Math.max(5, Math.round(size * 0.28)),
        background: adversarial
          ? 'linear-gradient(145deg, #ea580c 0%, #c2410c 100%)'
          : protestStyle
            ? 'linear-gradient(145deg, #e11d48 0%, #be123c 100%)'
            : 'linear-gradient(145deg, #ff5722 0%, #ff4500 100%)',
        border: `2px solid ${adversarial ? '#fdba74' : protestStyle ? '#fda4af' : '#ffccbc'}`,
        boxShadow: adversarial
          ? '0 0 14px rgba(234, 88, 12, 0.85)'
          : protestStyle
            ? '0 0 12px rgba(225, 29, 72, 0.8)'
            : '0 0 12px rgba(255, 69, 0, 0.75)',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#fff',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        fontWeight: 800,
        fontSize,
        lineHeight: 1,
        letterSpacing: '-0.05em',
        textTransform: 'lowercase',
      }}
    >
      r
    </div>
  );
}

// -- Telegram OSINT pins (HTML, above threat alert boxes) --
interface TelegramOsintMarkersProps {
  features: GeoJSON.Feature[];
  onEntityClick?: (entity: SelectedEntity | null) => void;
}

export function TelegramOsintMarkers({ features, onEntityClick }: TelegramOsintMarkersProps) {
  if (!features.length) return null;

  return (
    <>
      {features.map((feature) => {
        if (feature.geometry?.type !== 'Point') return null;
        const [lng, lat] = feature.geometry.coordinates as [number, number];
        const props = feature.properties || {};
        const id = String(props.id || '');
        if (!id) return null;
        const postCount = Number(props.post_count || 1);
        const size = postCount > 1 ? Math.min(30, 16 + Math.log2(postCount) * 5) : 16;

        return (
          <Marker
            key={`telegram-osint-${id}`}
            longitude={lng}
            latitude={lat}
            anchor="center"
            offset={TELEGRAM_MARKER_OFFSET}
            style={{ zIndex: 95 }}
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              onEntityClick?.({
                id,
                type: 'telegram_osint',
                name: String(props.name || 'Telegram OSINT'),
              });
            }}
          >
            <div
              title={`Telegram OSINT${postCount > 1 ? ` (${postCount} posts)` : ''}`}
              style={{ position: 'relative' }}
            >
              <TelegramOsintPin size={size} />
              <OsintPostCountBadge count={postCount} />
            </div>
          </Marker>
        );
      })}
    </>
  );
}

// -- Reddit OSINT pins (HTML, distinct from Telegram) --
interface RedditOsintMarkersProps {
  features: GeoJSON.Feature[];
  onEntityClick?: (entity: SelectedEntity | null) => void;
}

export function RedditOsintMarkers({ features, onEntityClick }: RedditOsintMarkersProps) {
  if (!features.length) return null;

  return (
    <>
      {features.map((feature) => {
        if (feature.geometry?.type !== 'Point') return null;
        const [lng, lat] = feature.geometry.coordinates as [number, number];
        const props = feature.properties || {};
        const id = String(props.id || '');
        if (!id) return null;
        const postCount = Number(props.post_count || 1);
        const adversarial = props.narrative_profile === 'adversarial';
        const protest = props.narrative_profile === 'protest';
        const size = postCount > 1 ? Math.min(30, 18 + Math.log2(postCount) * 4) : 18;

        return (
          <Marker
            key={`reddit-osint-${id}`}
            longitude={lng}
            latitude={lat}
            anchor="center"
            offset={REDDIT_MARKER_OFFSET}
            style={{ zIndex: 94 }}
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              onEntityClick?.({
                id,
                type: 'reddit_osint',
                name: String(props.name || 'Reddit OSINT'),
              });
            }}
          >
            <div
              title={`Reddit OSINT${postCount > 1 ? ` (${postCount} posts)` : ''}`}
              style={{ position: 'relative' }}
            >
              <RedditOsintPin size={size} adversarial={adversarial} protest={protest} />
              <OsintPostCountBadge count={postCount} />
            </div>
          </Marker>
        );
      })}
    </>
  );
}

