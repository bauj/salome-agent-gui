# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
# Tools > Plugins > AI tools: SALOME agent, MCP server.
# The plugins manager exec()s this file with a throwaway locals dict: a helper
# defined here is gone at click time, so each entry imports what it uses.
import salome_pluginsmanager


def openSalomeAgent(context):
    import sagui_launcher
    sagui_launcher.menu_window(context)


def startMcpServer(context):
    import sagui_launcher
    sagui_launcher.menu_mcp(context)


salome_pluginsmanager.AddFunction('AI tools/SALOME agent',
                                  'The agent that builds geometry and meshes in this study '
                                  'from a request in plain language',
                                  openSalomeAgent)
salome_pluginsmanager.AddFunction('AI tools/MCP server',
                                  'Serve this SALOME to Claude Code, Gemini CLI or another MCP '
                                  'client, and show how to connect them',
                                  startMcpServer)
