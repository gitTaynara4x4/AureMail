(() => {
  const currentUser = {
    email: "comercial@segsis.com.br",
    displayName: "Comercial",
    domain: "segsis.com.br"
  };

  const messages = [
    {
      id: "msg_001",
      folder: "inbox",
      unread: true,
      fromName: "Jurídico Segsis",
      fromEmail: "juridico@segsis.com.br",
      toEmail: "comercial@segsis.com.br",
      subject: "Documentação contratual para revisão",
      preview:
        "Precisamos revisar os anexos enviados pelo cliente antes de finalizar o retorno.",
      body: [
        "Bom dia, equipe.",
        "Precisamos revisar a documentação contratual enviada pelo cliente antes do retorno final. O material recebido contém cláusulas que precisam de validação jurídica e alinhamento com o escopo comercial.",
        "Peço que verifiquem os pontos principais e retornem com qualquer observação ainda hoje, para que possamos seguir com a negociação sem atraso.",
        "Atenciosamente,",
        "Jurídico Segsis"
      ],
      dateLabel: "Hoje, 09:18",
      listDate: "09:18",
      timestamp: "2026-04-02T09:18:00"
    },
    {
      id: "msg_002",
      folder: "inbox",
      unread: true,
      fromName: "Licitações",
      fromEmail: "licitacoes@segsis.com.br",
      toEmail: "comercial@segsis.com.br",
      subject: "Edital atualizado para conferência",
      preview:
        "O novo edital foi disponibilizado hoje cedo e precisa ser analisado pela equipe.",
      body: [
        "Pessoal, bom dia.",
        "O edital atualizado foi disponibilizado nesta manhã e já está pronto para análise.",
        "Assim que possível, preciso de uma conferência comercial para validar os itens mais sensíveis antes de montarmos o retorno oficial.",
        "Fico no aguardo.",
        "Equipe de Licitações"
      ],
      dateLabel: "Hoje, 08:42",
      listDate: "08:42",
      timestamp: "2026-04-02T08:42:00"
    },
    {
      id: "msg_003",
      folder: "inbox",
      unread: false,
      fromName: "Financeiro",
      fromEmail: "financeiro@segsis.com.br",
      toEmail: "comercial@segsis.com.br",
      subject: "Confirmação de pagamento recebida",
      preview:
        "Pagamento aprovado com sucesso. Segue comprovante para controle interno.",
      body: [
        "Olá.",
        "Confirmamos o recebimento do pagamento referente à proposta fechada nesta semana.",
        "O comprovante já foi anexado ao processo interno para controle financeiro e conciliação.",
        "Qualquer dúvida, seguimos à disposição.",
        "Financeiro"
      ],
      dateLabel: "Ontem, 16:11",
      listDate: "Ontem",
      timestamp: "2026-04-01T16:11:00"
    },
    {
      id: "msg_004",
      folder: "inbox",
      unread: false,
      fromName: "Cliente Externo",
      fromEmail: "contato@cliente-alpha.com.br",
      toEmail: "comercial@segsis.com.br",
      subject: "Solicitação de proposta comercial",
      preview:
        "Gostaríamos de receber uma proposta detalhada com escopo e prazo de implantação.",
      body: [
        "Boa tarde.",
        "Gostaríamos de receber uma proposta comercial detalhada, com escopo de implantação, prazo estimado e condições de atendimento.",
        "Caso possível, encaminhem também uma apresentação institucional resumida.",
        "Obrigado."
      ],
      dateLabel: "Ontem, 11:37",
      listDate: "Ontem",
      timestamp: "2026-04-01T11:37:00"
    },
    {
      id: "msg_005",
      folder: "inbox",
      unread: false,
      fromName: "Suporte Interno",
      fromEmail: "suporte@segsis.com.br",
      toEmail: "comercial@segsis.com.br",
      subject: "Ajuste de acesso concluído",
      preview:
        "O acesso solicitado foi liberado e já pode ser utilizado normalmente.",
      body: [
        "Olá.",
        "O ajuste de acesso solicitado foi concluído e a conta já está operando normalmente.",
        "Se notar qualquer comportamento inesperado, nos avise para verificarmos.",
        "Atenciosamente,",
        "Suporte Interno"
      ],
      dateLabel: "28 Mar, 14:20",
      listDate: "28 Mar",
      timestamp: "2026-03-28T14:20:00"
    },
    {
      id: "msg_006",
      folder: "sent",
      unread: false,
      fromName: "Comercial",
      fromEmail: "comercial@segsis.com.br",
      toEmail: "diretoria@segsis.com.br",
      subject: "Resumo da reunião com cliente estratégico",
      preview:
        "Encaminho o resumo dos principais pontos tratados na reunião de hoje.",
      body: [
        "Prezados,",
        "Encaminho o resumo dos principais pontos tratados na reunião de hoje com o cliente estratégico.",
        "Oportunidades comerciais foram identificadas e a receptividade foi positiva para avanço da negociação.",
        "Permaneço à disposição para detalharmos internamente.",
        "Comercial"
      ],
      dateLabel: "Hoje, 10:04",
      listDate: "10:04",
      timestamp: "2026-04-02T10:04:00"
    },
    {
      id: "msg_007",
      folder: "drafts",
      unread: false,
      fromName: "Comercial",
      fromEmail: "comercial@segsis.com.br",
      toEmail: "cliente-beta@empresa.com",
      subject: "Minuta de proposta em elaboração",
      preview:
        "Rascunho salvo para continuidade da proposta comercial.",
      body: [
        "Olá.",
        "Segue rascunho inicial da proposta comercial. Ainda faltam ajustes de prazo e escopo antes do envio final."
      ],
      dateLabel: "Hoje, 07:55",
      listDate: "07:55",
      timestamp: "2026-04-02T07:55:00"
    },
    {
      id: "msg_008",
      folder: "trash",
      unread: false,
      fromName: "Newsletter",
      fromEmail: "news@exemplo.com",
      toEmail: "comercial@segsis.com.br",
      subject: "Novidades do mercado",
      preview:
        "Mensagem movida para a lixeira na demonstração visual.",
      body: [
        "Conteúdo promocional removido da caixa principal."
      ],
      dateLabel: "27 Mar, 09:10",
      listDate: "27 Mar",
      timestamp: "2026-03-27T09:10:00"
    }
  ];

  window.AUREMAIL_MOCK = {
    currentUser,
    messages
  };
})();