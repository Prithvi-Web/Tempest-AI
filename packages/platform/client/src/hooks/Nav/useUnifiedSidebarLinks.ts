import { useMemo } from 'react';
import { useRecoilValue } from 'recoil';
import { BarChart3, Boxes, MessagesSquare, Zap } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useUserKeyQuery } from 'librechat-data-provider/react-query';
import { getConfigDefaults, getEndpointField, SystemRoles } from 'librechat-data-provider';
import type { TEndpointsConfig } from 'librechat-data-provider';
import type { NavLink } from '~/common';
import { useGetEndpointsQuery, useGetStartupConfig, useInsightsAccessQuery } from '~/data-provider';
import ConversationsSection from '~/components/UnifiedSidebar/ConversationsSection';
import useSideNavLinks from '~/hooks/Nav/useSideNavLinks';
/** Tempest seam (ADR-0082): the models destination opens the app's ONE settings home on its
 * Models tab, rather than being a second settings page. */
import { openSettingsHome } from '../../../tempest/settings/home';
import { TEMPEST_MODELS_TAB } from '../../../tempest/settings/tabIds';
import { useAuthContext } from '~/hooks';
import store from '~/store';

const defaultInterface = getConfigDefaults().interface;

export default function useUnifiedSidebarLinks() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuthContext();
  /** Selector instead of the full conversation atom: the links only depend on
   * the endpoint, so parameter edits and other conversation writes stay out. */
  const endpoint = useRecoilValue(store.conversationEndpointByIndex(0)) ?? undefined;
  const { data: startupConfig } = useGetStartupConfig();
  const { data: endpointsConfig = {} as TEndpointsConfig } = useGetEndpointsQuery();

  const interfaceConfig = useMemo(
    () => startupConfig?.interface ?? defaultInterface,
    [startupConfig],
  );
  const insightsFeatureEnabled = startupConfig?.insightsEnabled === true;
  const { data: insightsAccess } = useInsightsAccessQuery(user?.id, {
    enabled: user?.role === SystemRoles.ADMIN && insightsFeatureEnabled,
  });

  const endpointType = useMemo(
    () => getEndpointField(endpointsConfig, endpoint, 'type'),
    [endpoint, endpointsConfig],
  );

  const userProvidesKey = useMemo(
    () => !!(endpointsConfig?.[endpoint ?? '']?.userProvide ?? false),
    [endpointsConfig, endpoint],
  );

  const { data: keyExpiry = { expiresAt: undefined } } = useUserKeyQuery(endpoint ?? '');

  const keyProvided = useMemo(
    () => (userProvidesKey ? !!(keyExpiry.expiresAt ?? '') : true),
    [keyExpiry.expiresAt, userProvidesKey],
  );

  const sideNavLinks = useSideNavLinks({
    keyProvided,
    endpoint,
    endpointType,
    interfaceConfig,
    endpointsConfig,
    includeHidePanel: false,
  });

  const links = useMemo(() => {
    const conversationLink: NavLink = {
      title: 'com_ui_chat_history',
      label: '',
      icon: MessagesSquare,
      id: 'conversations',
      Component: ConversationsSection,
    };

    /** Tempest seam (C3): the absorbed proof surface, a first-class destination beside the
     * chat — same navigation pattern as the insights link. The title is a real locale key as
     * of ADR-0082 (`NavLink.title` is `TranslationKeys`, and the raw string here had been an
     * invisible type error since C3 — the vendored client's own tsc is red at baseline, so
     * nothing was reading it). Ledger row in packages/platform/UPSTREAM.md. */
    const tempestLink: NavLink = {
      title: 'com_tempest_nav_tempest',
      label: '',
      icon: Zap,
      id: 'tempest',
      onClick: () => {
        if (!location.pathname.startsWith('/tempest')) {
          navigate('/tempest');
        }
      },
    };

    /** Tempest seam (ADR-0082): the models destination, on the MAIN rail.
     *
     * The owner's requirement, in their words: *"I would like to be able to download local
     * models on the vertical navigation bar… people should be able to use local models or api
     * keys for that."* Choosing how the assistant thinks is a chat-app decision, and it was
     * three clicks deep behind the proof surface — which is a TOOL the assistant uses
     * (ADR-0067), not the front door.
     *
     * It opens the ONE settings home rather than navigating to a page of its own: local
     * models and provider keys are the same decision and now sit in the same tab, beside
     * every other setting in the app. */
    const modelsLink: NavLink = {
      title: 'com_tempest_settings_tab_models',
      label: '',
      icon: Boxes,
      id: 'tempest-models',
      onClick: () => openSettingsHome(TEMPEST_MODELS_TAB),
    };

    if (!insightsFeatureEnabled || insightsAccess?.access !== true) {
      return [conversationLink, modelsLink, tempestLink, ...sideNavLinks];
    }

    const insightsLink: NavLink = {
      title: 'com_insights_navigation',
      label: '',
      icon: BarChart3,
      id: 'insights',
      onClick: () => {
        if (!location.pathname.startsWith('/insights')) {
          navigate('/insights');
        }
      },
    };
    const mcpIndex = sideNavLinks.findIndex((link) => link.id === 'mcp-builder');
    const nextLinks = [...sideNavLinks];
    nextLinks.splice(mcpIndex >= 0 ? mcpIndex + 1 : nextLinks.length, 0, insightsLink);

    return [conversationLink, modelsLink, tempestLink, ...nextLinks];
  }, [insightsAccess?.access, insightsFeatureEnabled, location.pathname, navigate, sideNavLinks]);

  return links;
}
