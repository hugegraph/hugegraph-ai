# HugeGraph-ai 固定工作流框架设计和用例移植

本文档将 HugeGraph 固定工作流框架设计和用例移植转换为一系列可执行的编码任务。

## 1. schedule_flow设计与实现

- [x] **1.1 构建Scheduler框架1.0**
    -   需要能够复用已经创建过的Pipeline(Pipeline Pooling)
    -   使用CGraph(Graph-based engine)作为底层执行引擎
    -   不同Node之间松耦合

- [ ] **1.2 优化Scheduler框架资源配置**
    -   支持用户配置底层线程池参数
    -   现有的workflow可能会根据输入有细小的变化，导致相同的用例得到不同的workflow，怎么解决这个问题呢？

- [ ] **1.3 优化Scheduler框架资源使用**
    -   根据负载控制每个PipelineManager管理的Pipeline数量，实现动态扩缩容

## 2. 固定工作流用例移植

- [x] **2.1 build_vector_index workflow移植**
- [x] **2.2 graph_extract workflow移植**
- [ ] **2.3 load_into_graphdb workflow移植**
