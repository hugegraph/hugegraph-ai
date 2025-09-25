from PyCGraph import GNode, CStatus
from hugegraph_llm.nodes.util import init_context
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class BaseNode(GNode):
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def init(self):
        return init_context(self)

    def node_init(self):
        """
        节点初始化方法，子类可重写。
        返回CStatus对象，表示初始化是否成功。
        """
        return CStatus()

    def run(self):
        """
        节点运行主逻辑，子类可重写。
        返回CStatus对象，表示运行是否成功。
        """
        sts = self.node_init()
        if sts.isErr():
            return sts
        self.context.lock()
        data_json = self.context.to_json()
        self.context.unlock()
        res = self.operator_schedule(data_json)
        self.context.lock()
        self.context.assign_from_json(res)
        self.context.unlock()
        return CStatus()

    def operator_schedule(self, data_json):
        """
        节点调度operator的接口，子类可重写。
        返回CStatus对象，表示调度是否成功。
        """
        pass
