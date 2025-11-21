import axios from 'axios';
import type { OrchestratorReport, AgentStatus, AgentLogs } from '../types';

const API_BASE = '/api';

// Retrieve current status from all agents (triggers execution)
export const retrieveStatus = async (): Promise<OrchestratorReport> => {
  const { data } = await axios.post(`${API_BASE}/retrieve-status`);
  return data;
};

// Get current status of all agents
export const getAgentStatuses = async (): Promise<Record<string, AgentStatus>> => {
  const { data } = await axios.get(`${API_BASE}/agent-status`);
  return data;
};

// Get detailed logs for specific agent
export const getAgentLogs = async (agentName: string): Promise<AgentLogs> => {
  const { data } = await axios.get(`${API_BASE}/agent-logs/${agentName}`);
  return data;
};
